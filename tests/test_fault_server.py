"""Black-box evidence that the LOCAL SIMULATOR exercises real network faults."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest
import websockets
from mock_bybit import utc_ms

D = Decimal


def signed_request(
    server, method: str, path: str, *, params: dict | None = None, payload: dict | None = None
) -> httpx.Request:
    """Independent V5 signer: sign exact wire bytes, not implementation helpers."""
    body = json.dumps(payload, separators=(",", ":")) if payload is not None else ""
    request = httpx.Request(method, server.base_url + path, params=params, content=body)
    timestamp, recv = str(utc_ms()), "5000"
    material = request.url.query.decode() if method == "GET" else body
    prefix = timestamp + server.state.api_key + recv
    signature = hmac.new(
        server.state.api_secret.encode(), (prefix + material).encode(), hashlib.sha256
    ).hexdigest()
    request.headers.update(
        {
            "X-BAPI-API-KEY": server.state.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv,
            "X-BAPI-SIGN": signature,
            "Content-Type": "application/json",
        }
    )
    return request


def order_payload(
    link: str = "qa-order-1",
    *,
    qty: str = "0.010",
    idx: int = 1,
    limit: bool = False,
    reduce: bool = False,
) -> dict:
    side = ("Sell" if idx == 1 else "Buy") if reduce else ("Buy" if idx == 1 else "Sell")
    body = {
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": side,
        "positionIdx": idx,
        "orderType": "Limit" if limit else "Market",
        "qty": qty,
        "orderLinkId": link,
        "reduceOnly": reduce,
    }
    if limit:
        body["price"] = "68000"
    return body


async def ws_private(server):
    websocket = await websockets.connect(server.ws_url + "/v5/private")
    expires = utc_ms() + 10000
    signature = hmac.new(
        server.state.api_secret.encode(), f"GET/realtime{expires}".encode(), hashlib.sha256
    ).hexdigest()
    await websocket.send(
        json.dumps({"op": "auth", "args": [server.state.api_key, expires, signature]})
    )
    authenticated = json.loads(await websocket.recv())
    assert authenticated["success"] is True
    await websocket.send(
        json.dumps({"op": "subscribe", "args": ["order", "execution", "position", "wallet"]})
    )
    subscribed = json.loads(await websocket.recv())
    assert subscribed["success"] is True
    return websocket


@pytest.mark.asyncio
async def test_signed_requests_and_invalid_signatures_cannot_create_orders(local_bybit_server):
    server = local_bybit_server
    async with httpx.AsyncClient(trust_env=False) as client:
        valid = await client.send(
            signed_request(
                server,
                "GET",
                "/v5/account/wallet-balance",
                params={"accountType": "UNIFIED", "coin": "USDT"},
            )
        )
        assert valid.json()["retCode"] == 0
        assert D(valid.json()["result"]["list"][0]["totalEquity"]) == D("100000")
        bad = signed_request(server, "POST", "/v5/order/create", payload=order_payload())
        bad.headers["X-BAPI-SIGN"] = "0" * 64
        rejected = await client.send(bad)
        assert rejected.json()["retCode"] == 10004
        unsigned = await client.post(server.base_url + "/v5/order/create", json=order_payload())
        assert unsigned.json()["retCode"] == 10003
    assert not server.state.orders


@pytest.mark.asyncio
async def test_acknowledgement_precedes_delayed_fill_and_real_quantity(local_bybit_server):
    server = local_bybit_server
    server.state.fill_delay = 0.08
    server.state.fill_fraction = D("0.4")
    async with httpx.AsyncClient(trust_env=False) as client:
        created = await client.send(
            signed_request(server, "POST", "/v5/order/create", payload=order_payload())
        )
    order_id = created.json()["result"]["orderId"]
    assert server.state.orders[order_id]["orderStatus"] == "New"
    assert server.state.position_book[1]["qty"] == 0
    await asyncio.sleep(0.12)
    order = server.state.orders[order_id]
    assert order["orderStatus"] == "PartiallyFilled"
    assert D(order["cumExecQty"]) == D("0.004")
    assert D(order["leavesQty"]) == D("0.006")
    assert server.state.position_book[1]["qty"] == D("0.004")
    assert D(server.state.executions[0]["execFee"]) == D("0.004") * D("67000") * D("0.0006")


@pytest.mark.asyncio
async def test_accepted_timeout_has_one_exchange_order_and_can_be_found_in_history(
    local_bybit_server,
):
    server = local_bybit_server
    server.state.inject_fault("/v5/order/create", "accepted_timeout", delay=0.12)
    async with httpx.AsyncClient(timeout=0.03, trust_env=False) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.send(
                signed_request(
                    server, "POST", "/v5/order/create", payload=order_payload("timeout-ack")
                )
            )
    assert len(server.state.orders) == 1
    assert len(server.state.executions) == 1
    async with httpx.AsyncClient(trust_env=False) as client:
        realtime = await client.send(
            signed_request(
                server,
                "GET",
                "/v5/order/realtime",
                params={"orderLinkId": "timeout-ack", "openOnly": 0},
            )
        )
        history = await client.send(
            signed_request(
                server, "GET", "/v5/order/history", params={"orderLinkId": "timeout-ack"}
            )
        )
    assert realtime.json()["result"]["list"] == []
    assert len(history.json()["result"]["list"]) == 1
    assert history.json()["result"]["list"][0]["orderStatus"] == "Filled"
    assert sum(c["path"] == "/v5/order/create" for c in server.state.calls) == 1


@pytest.mark.asyncio
async def test_fault_injection_has_bounded_429_5xx_and_rejection(local_bybit_server):
    server = local_bybit_server
    server.state.inject_fault("/v5/market/tickers", "429")
    server.state.inject_fault("/v5/market/tickers", "5xx")
    async with httpx.AsyncClient(trust_env=False) as client:
        first = await client.get(server.base_url + "/v5/market/tickers")
        second = await client.get(server.base_url + "/v5/market/tickers")
        third = await client.get(server.base_url + "/v5/market/tickers")
        server.state.reject_next_create = True
        rejected = await client.send(
            signed_request(server, "POST", "/v5/order/create", payload=order_payload())
        )
    assert first.status_code == 429
    assert first.headers["X-Bapi-Limit-Status"] == "0"
    assert second.status_code == 503
    assert third.status_code == 200
    assert rejected.json()["retCode"] == 110007
    assert not server.state.orders


@pytest.mark.asyncio
async def test_duplicate_client_link_id_is_rejected_without_second_fill(local_bybit_server):
    server = local_bybit_server
    async with httpx.AsyncClient(trust_env=False) as client:
        first = await client.send(
            signed_request(server, "POST", "/v5/order/create", payload=order_payload("one-link"))
        )
        second = await client.send(
            signed_request(server, "POST", "/v5/order/create", payload=order_payload("one-link"))
        )
    assert first.json()["retCode"] == 0
    assert second.json()["retCode"] == 110072
    assert len(server.state.orders) == len(server.state.executions) == 1
    assert server.state.position_book[1]["qty"] == D("0.010")


@pytest.mark.asyncio
async def test_execution_before_filled_order_and_duplicate_ws_event(local_bybit_server):
    server = local_bybit_server
    server.state.execution_first = True
    server.state.duplicate_executions = True
    server.state.stale_order_after_fill = True
    websocket = await ws_private(server)
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            await client.send(
                signed_request(server, "POST", "/v5/order/create", payload=order_payload())
            )
        messages = [json.loads(await asyncio.wait_for(websocket.recv(), 1)) for _ in range(7)]
        assert messages[0]["topic"] == "order" and messages[0]["data"][0]["orderStatus"] == "New"
        assert messages[1]["topic"] == "execution"
        assert messages[2]["topic"] == "order" and messages[2]["data"][0]["orderStatus"] == "Filled"
        assert messages[3]["topic"] == "execution"
        assert messages[1]["data"][0]["execId"] == messages[3]["data"][0]["execId"]
        assert messages[4]["data"][0]["orderStatus"] == "New"
        assert len(server.state.executions) == 1
    finally:
        await websocket.close()


@pytest.mark.asyncio
async def test_private_subscription_requires_auth_and_disconnect_is_real(local_bybit_server):
    server = local_bybit_server
    async with websockets.connect(server.ws_url + "/v5/private") as websocket:
        await websocket.send(json.dumps({"op": "subscribe", "args": ["execution"]}))
        denied = json.loads(await websocket.recv())
        assert denied["success"] is False
        assert denied["ret_msg"] == "authentication required"
    websocket = await ws_private(server)
    await server.state.disconnect_private()
    with pytest.raises(websockets.exceptions.ConnectionClosed):
        await asyncio.wait_for(websocket.recv(), 1)
    assert websocket.close_code == 1012


@pytest.mark.asyncio
async def test_public_ticker_heartbeat_and_updates(local_bybit_server):
    server = local_bybit_server
    async with websockets.connect(server.ws_url + "/v5/public/linear") as websocket:
        await websocket.send(json.dumps({"op": "subscribe", "args": ["tickers.BTCUSDT"]}))
        assert json.loads(await websocket.recv())["success"] is True
        ticker = json.loads(await websocket.recv())
        assert ticker["data"]["lastPrice"] == "67000"
        await websocket.send(json.dumps({"op": "ping"}))
        assert json.loads(await websocket.recv())["op"] == "pong"
        await server.state.advance_market(D("68000"))
        assert json.loads(await websocket.recv())["data"]["lastPrice"] == "68000"


@pytest.mark.asyncio
async def test_reduce_only_tp_preserves_opposite_hedge_position(local_bybit_server):
    server = local_bybit_server
    async with httpx.AsyncClient(trust_env=False) as client:
        long = await client.send(
            signed_request(server, "POST", "/v5/order/create", payload=order_payload("long", idx=1))
        )
        short = await client.send(
            signed_request(
                server, "POST", "/v5/order/create", payload=order_payload("short", idx=2)
            )
        )
        tp = await client.send(
            signed_request(
                server,
                "POST",
                "/v5/order/create",
                payload=order_payload("long-tp", idx=1, limit=True, reduce=True),
            )
        )
        assert long.json()["retCode"] == short.json()["retCode"] == tp.json()["retCode"] == 0
    await server.state.advance_market(D("68000"))
    assert server.state.position_book[1]["qty"] == 0
    assert server.state.position_book[2]["qty"] == D("0.010")
    assert server.state.position_book[2]["average"] == D("67000")
    assert server.state.executions[-1]["closedSize"] == "0.010"
    assert D(server.state.executions[-1]["execPnl"]) == D("10")


@pytest.mark.asyncio
async def test_cancel_pending_order_and_history_pagination(local_bybit_server):
    server = local_bybit_server
    server.state.market_auto_fill = False
    server.state.page_size = 1
    async with httpx.AsyncClient(trust_env=False) as client:
        ids = []
        for n in range(3):
            created = await client.send(
                signed_request(
                    server, "POST", "/v5/order/create", payload=order_payload(f"page-{n}")
                )
            )
            ids.append(created.json()["result"]["orderId"])
        canceled = await client.send(
            signed_request(
                server, "POST", "/v5/order/cancel", payload={"symbol": "BTCUSDT", "orderId": ids[0]}
            )
        )
        assert canceled.json()["retCode"] == 0
        collected, cursor = [], ""
        while True:
            response = await client.send(
                signed_request(server, "GET", "/v5/order/history", params={"cursor": cursor})
            )
            collected.extend(response.json()["result"]["list"])
            cursor = response.json()["result"]["nextPageCursor"]
            if not cursor:
                break
    assert len(collected) == 3
    assert collected[0]["orderStatus"] == "Cancelled"
    assert not server.state.executions


def execution_payload(
    exec_id: str,
    link: str,
    qty: str,
    price: str,
    *,
    fee: str = "0",
    close: bool = False,
    order_id: str | None = None,
) -> dict:
    return {
        "execId": exec_id,
        "orderId": order_id or "exchange-" + link,
        "orderLinkId": link,
        "symbol": "BTCUSDT",
        "side": "Sell" if close else "Buy",
        "positionIdx": 1,
        "execType": "Trade",
        "execQty": qty,
        "execPrice": price,
        "execFee": fee,
        "execTime": str(utc_ms()),
    }


@pytest.mark.asyncio
async def test_partial_entry_close_then_late_fill_preserves_remaining_cost_basis(tmp_path):
    """Independent cash-flow invariant; sold units cannot dilute future cost basis."""
    from gridbot.models import Environment, OrderIntent, Side
    from gridbot.persistence import Store

    store = Store(tmp_path / "partial-sequence.sqlite")
    await store.initialize()
    try:
        entry = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="partial-entry",
            side=Side.LONG,
            qty=D("20"),
        )
        await store.claim_intent(entry)
        await store.apply_execution(
            execution_payload("first-10", entry.order_link_id, "10", "100", fee="1")
        )
        first_close = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="close-first-4",
            side=Side.LONG,
            qty=D("4"),
            reduce_only=True,
            purpose="TP",
            parent_link_id=entry.order_link_id,
        )
        await store.claim_intent(first_close)
        await store.apply_execution(
            execution_payload(
                "close-4", first_close.order_link_id, "4", "110", fee="0.44", close=True
            )
        )
        await store.apply_execution(
            execution_payload("last-10", entry.order_link_id, "10", "200", fee="2")
        )
        lots = await store.lots()
        assert len(lots) == 1
        assert D(lots[0]["qty"]) == D("16")
        # Six surviving units cost 600 and ten new units cost 2000.
        assert D(lots[0]["entry"]) == D("2600") / D("16")
        # Only 6/10 of the first entry fee remains, plus the second entry fee.
        assert D(lots[0]["fees"]) == D("0.6") + D("2")
        final_close = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="close-final-16",
            side=Side.LONG,
            qty=D("16"),
            reduce_only=True,
            purpose="CLOSE",
            parent_link_id=entry.order_link_id,
        )
        await store.claim_intent(final_close)
        await store.apply_execution(
            execution_payload(
                "close-16", final_close.order_link_id, "16", "210", fee="3.36", close=True
            )
        )
        assert await store.lots() == []
        realized = sum((D(e["realized_pnl"]) for e in await store.executions()), D(0))
        # Cash received: 4*110+16*210. Original entry cost: 10*100+10*200.
        assert realized == D("440") + D("3360") - D("1000") - D("2000")
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_field,bad_value",
    [
        ("execFee", "NaN"),
        ("execPrice", "Infinity"),
        ("orderId", "foreign-order"),
        ("positionIdx", 2),
    ],
)
async def test_execution_integrity_failure_is_transactional(tmp_path, bad_field, bad_value):
    from gridbot.errors import DatabaseError
    from gridbot.models import Environment, OrderIntent, Side
    from gridbot.persistence import Store

    store = Store(tmp_path / "integrity.sqlite")
    await store.initialize()
    try:
        entry = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="integrity-entry",
            side=Side.LONG,
            qty=D("2"),
        )
        await store.claim_intent(entry)
        await store.update_order(entry.order_link_id, exchange_id="expected-order")
        payload = execution_payload(
            "bad-execution", entry.order_link_id, "1", "100", fee="0.1", order_id="expected-order"
        )
        payload[bad_field] = bad_value
        with pytest.raises(DatabaseError):
            await store.apply_execution(payload)
        row = await store.get_order(entry.order_link_id)
        assert row["executed_qty"] == "0"
        assert row["order_id"] == "expected-order"
        assert await store.lots() == []
        assert await store.executions() == []
    finally:
        await store.close()


def make_adapter(server, *, live: bool = False, **kwargs):
    from gridbot.exchange import BybitDemoAdapter, BybitMainnetAdapter
    from gridbot.models import Credentials, Environment
    from mock_bybit import LoopbackTransport

    transport = LoopbackTransport(server)
    credentials = Credentials(
        environment=Environment.MAINNET if live else Environment.DEMO,
        api_key=server.state.api_key,
        api_secret=server.state.api_secret,
    )
    adapter = (BybitMainnetAdapter if live else BybitDemoAdapter)(
        credentials, transport=transport, **kwargs
    )
    return adapter, transport


@pytest.mark.asyncio
async def test_production_adapter_real_signed_local_network_and_demo_public_routing(
    local_bybit_server,
):
    server = local_bybit_server
    adapter, transport = make_adapter(server)
    try:
        account = await adapter.account()
        instrument = await adapter.instrument("BTCUSDT")
        ticker = await adapter.ticker("BTCUSDT")
        candles = await adapter.candles("BTCUSDT", limit=5)
        assert account.uid == "424242" and account.permissions and account.hedge_mode
        assert account.equity == D("100000")
        assert account.available_balance == D("100000")
        assert instrument.qty_step == D("0.001") and instrument.tick_size == D("0.1")
        assert ticker == D("67000")
        assert len(candles) == 5 and candles[0]["time"] < candles[-1]["time"]
        private_urls = [url for url in transport.requested_urls if "/v5/market/" not in url]
        public_urls = [url for url in transport.requested_urls if "/v5/market/" in url]
        assert private_urls and all(
            url.startswith("https://api-demo.bybit.com/") for url in private_urls
        )
        assert public_urls and all(url.startswith("https://api.bybit.com/") for url in public_urls)
        assert all("testnet" not in url for url in transport.requested_urls)
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_production_adapter_mutation_timeout_never_retries_and_finds_history(
    local_bybit_server,
):
    from gridbot.errors import UncertainOrderError
    from gridbot.models import Environment, OrderIntent, Side

    server = local_bybit_server
    adapter, _ = make_adapter(server)
    adapter._client.timeout = httpx.Timeout(0.03)
    server.state.inject_fault("/v5/order/create", "accepted_timeout", delay=0.12)
    intent = OrderIntent(
        environment=Environment.DEMO,
        symbol="BTCUSDT",
        order_link_id="real-adapter-timeout",
        side=Side.LONG,
        qty=D("0.010"),
    )
    try:
        with pytest.raises(UncertainOrderError):
            await adapter.create_order(intent)
        adapter._client.timeout = httpx.Timeout(1)
        recovered = await adapter.find_order("BTCUSDT", intent.order_link_id)
        assert recovered is not None
        assert recovered["orderLinkId"] == intent.order_link_id
        assert recovered["orderStatus"] == "Filled"
        assert len(server.state.orders) == len(server.state.executions) == 1
        assert sum(c["path"] == "/v5/order/create" for c in server.state.calls) == 1
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_production_adapter_safe_get_backoff_is_bounded(local_bybit_server):
    from gridbot.errors import NetworkError

    delays = []

    async def record_sleep(delay):
        delays.append(delay)

    server = local_bybit_server
    adapter, _ = make_adapter(server, sleep=record_sleep)
    server.state.inject_fault("/v5/market/tickers", "429", count=4)
    try:
        with pytest.raises(NetworkError):
            await adapter.ticker("BTCUSDT")
        assert len(delays) == 3
        assert all(delay >= 0.5 for delay in delays)
        assert sum(c["path"] == "/v5/market/tickers" for c in server.state.calls) == 4
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_production_mainnet_mutations_block_without_both_backend_authorizations(
    local_bybit_server,
):
    from gridbot.errors import RiskError
    from gridbot.models import Environment, OrderIntent, Side

    server = local_bybit_server
    adapter, transport = make_adapter(server, live=True)
    intent = OrderIntent(
        environment=Environment.MAINNET,
        symbol="BTCUSDT",
        order_link_id="forbidden-live",
        side=Side.LONG,
        qty=D("0.010"),
    )
    try:
        for allow, confirmed in [(False, False), (True, False), (False, True)]:
            adapter.set_live_authorization(allow, confirmed)
            with pytest.raises(RiskError):
                await adapter.create_order(intent)
        assert not server.state.orders and not transport.requested_urls
        # Read-only LIVE account inspection is allowed; no actual mainnet network call.
        account = await adapter.account()
        assert account.uid == "424242"
        assert all(url.startswith("https://api.bybit.com/") for url in transport.requested_urls)
        assert not server.state.orders
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_production_adapter_pagination_retrieves_all_open_orders(local_bybit_server):
    from gridbot.models import Environment, OrderIntent, Side

    server = local_bybit_server
    server.state.market_auto_fill = False
    server.state.page_size = 1
    adapter, _ = make_adapter(server)
    try:
        for n in range(3):
            await adapter.create_order(
                OrderIntent(
                    environment=Environment.DEMO,
                    symbol="BTCUSDT",
                    order_link_id=f"adapter-page-{n}",
                    side=Side.LONG,
                    qty=D("0.010"),
                )
            )
        orders = await adapter.open_orders("BTCUSDT")
        assert len(orders) == 3
        assert {o["orderLinkId"] for o in orders} == {f"adapter-page-{n}" for n in range(3)}
        assert sum(c["path"] == "/v5/order/realtime" for c in server.state.calls) == 3
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_filled_order_report_before_execution_blocks_new_entry_risk(tmp_path):
    """A terminal order ACK cannot erase unaccounted exposure while fills lag."""
    import time
    from types import SimpleNamespace

    from gridbot.models import (
        AccountInfo,
        Environment,
        Instrument,
        OrderIntent,
        Side,
        StrategyConfig,
    )
    from gridbot.orders import OrderManager
    from gridbot.persistence import Store
    from gridbot.risk import RiskEngine
    from gridbot.runtime import BotRuntime

    runtime = BotRuntime(tmp_path)
    runtime.store = Store(tmp_path / "lagged-fill.sqlite")
    await runtime.store.initialize()
    runtime.price = D("100")
    runtime.account = AccountInfo(
        uid="42",
        account_type="UNIFIED",
        uta_status=5,
        equity=D("100000"),
        available_balance=D("100000"),
        hedge_mode=True,
        permissions=True,
        leverage_long=D(1),
        leverage_short=D(1),
    )
    runtime.instrument = Instrument(
        symbol="BTCUSDT",
        tick_size=D("0.1"),
        qty_step=D("1"),
        min_qty=D(1),
        max_qty=D(100),
        max_market_qty=D(100),
        min_notional=D(1),
    )
    runtime.config = StrategyConfig(order_size_usdt=D("1000"))
    runtime.connected = runtime.public_connected = runtime.private_connected = (
        runtime.reconciled
    ) = True
    runtime.last_public = time.monotonic()
    runtime.status = "RUNNING"
    runtime.manager = OrderManager(
        SimpleNamespace(environment=Environment.DEMO),
        runtime.store,
        RiskEngine(),
        runtime.config,
        runtime.instrument,
        runtime.risk_context,
        runtime.notify,
    )
    try:
        entry = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="lagged-entry",
            side=Side.LONG,
            qty=D("10"),
        )
        await runtime.store.claim_intent(entry)
        await runtime.store.apply_execution(
            execution_payload("first-4", entry.order_link_id, "4", "100")
        )
        await runtime.manager.order_event(
            {
                "orderId": "exchange-lagged-entry",
                "orderLinkId": entry.order_link_id,
                "orderStatus": "Filled",
                "cumExecQty": "10",
            }
        )
        proposed = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="must-block-entry",
            side=Side.SHORT,
            qty=D("1"),
        )
        context = await runtime.risk_context(proposed)
        assert context.reconciled is False, (
            "Missing six execution units must block new orders until reconciliation"
        )
    finally:
        await runtime.store.close()


@pytest.mark.asyncio
async def test_partial_fill_tp_is_actual_quantity_pause_preserves_tp_and_opposite_side(
    local_bybit_server, tmp_path
):
    import time

    from gridbot.models import Environment, OrderIntent, Side, StrategyConfig
    from gridbot.orders import OrderManager
    from gridbot.persistence import Store
    from gridbot.risk import RiskEngine
    from gridbot.runtime import BotRuntime

    server = local_bybit_server
    server.state.market_auto_fill = False
    adapter, _ = make_adapter(server)
    runtime = BotRuntime(tmp_path)
    runtime.store = Store(tmp_path / "protected-partial.sqlite")
    await runtime.store.initialize()
    runtime.adapter = adapter
    runtime.account = await adapter.account()
    runtime.instrument = await adapter.instrument("BTCUSDT")
    await runtime._fetch_prices()
    runtime.config = StrategyConfig(order_size_usdt=D("1000"))
    runtime.status = "RUNNING"
    runtime.connected = runtime.public_connected = runtime.private_connected = (
        runtime.reconciled
    ) = True
    runtime.last_public = time.monotonic()
    runtime.manager = OrderManager(
        adapter,
        runtime.store,
        RiskEngine(),
        runtime.config,
        runtime.instrument,
        runtime.risk_context,
        runtime.notify,
    )
    try:
        long = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="actual-long",
            side=Side.LONG,
            qty=D("0.010"),
        )
        short = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="actual-short",
            side=Side.SHORT,
            qty=D("0.010"),
        )
        long_row = await runtime.manager.submit(long)
        short_row = await runtime.manager.submit(short)
        long_execution = await server.state.fill(long_row["order_id"], D("0.004"))
        short_execution = await server.state.fill(short_row["order_id"])
        await runtime.manager.execution_event(long_execution)
        await runtime.manager.execution_event(short_execution)
        await runtime.manager.order_event(server.state.orders[long_row["order_id"]])
        await runtime.manager.order_event(server.state.orders[short_row["order_id"]])
        await runtime.manager.ensure_protection()
        orders = await runtime.store.orders()
        tps = [o for o in orders if o["purpose"] == "TP"]
        assert len(tps) == 2
        long_tp = next(o for o in tps if o["side"] == "LONG")
        short_tp = next(o for o in tps if o["side"] == "SHORT")
        assert D(long_tp["qty"]) == D("0.004")
        assert D(short_tp["qty"]) == D("0.010")
        assert D(long_tp["price"]) == D("67670")
        assert D(short_tp["price"]) == D("66330")
        assert await runtime.manager.execution_event(long_execution) is False
        await runtime.manager.ensure_protection()
        assert len([o for o in await runtime.store.orders() if o["purpose"] == "TP"]) == 2
        runtime.status = "PAUSED"
        await runtime.manager.pause_entries()
        assert server.state.orders[long_row["order_id"]]["orderStatus"] == "Cancelled"
        assert server.state.orders[long_tp["order_id"]]["orderStatus"] == "New"
        assert server.state.orders[short_tp["order_id"]]["orderStatus"] == "New"
        assert server.state.position_book[1]["qty"] == D("0.004")
        assert server.state.position_book[2]["qty"] == D("0.010")
        await server.state.advance_market(D("67670"))
        close_execution = server.state.executions[-1]
        assert close_execution["orderId"] == long_tp["order_id"]
        await runtime.manager.execution_event(close_execution)
        await runtime.manager.order_event(server.state.orders[long_tp["order_id"]])
        assert server.state.position_book[1]["qty"] == 0
        assert server.state.position_book[2]["qty"] == D("0.010")
        lots = await runtime.store.lots()
        assert len(lots) == 1 and lots[0]["side"] == "SHORT"
        assert D((await runtime.store.executions())[-1]["realized_pnl"]) == D("2.680")
    finally:
        await adapter.close()
        await runtime.store.close()


@pytest.mark.asyncio
async def test_close_all_large_position_never_removes_tp_before_feasible_closure(
    local_bybit_server, tmp_path
):
    """Many valid fills can exceed one market order's size; preserve protection."""
    import time

    from gridbot.errors import BotError
    from gridbot.models import Environment, OrderIntent, Side, StrategyConfig
    from gridbot.orders import OrderManager
    from gridbot.persistence import Store
    from gridbot.risk import RiskEngine
    from gridbot.runtime import BotRuntime

    server = local_bybit_server
    server.state.equity = server.state.available_balance = D("10000000")
    server.state.market_auto_fill = False
    adapter, _ = make_adapter(server)
    runtime = BotRuntime(tmp_path)
    runtime.store = Store(tmp_path / "large-close.sqlite")
    await runtime.store.initialize()
    runtime.adapter = adapter
    runtime.account = await adapter.account()
    runtime.instrument = await adapter.instrument("BTCUSDT")
    await runtime._fetch_prices()
    runtime.config = StrategyConfig(
        order_size_usdt=D("700000"),
        max_exposure_usdt=D("10000000"),
        max_recovery_exposure_usdt=D("5000000"),
        max_daily_loss_usdt=D("10000"),
    )
    runtime.connected = runtime.public_connected = runtime.private_connected = (
        runtime.reconciled
    ) = True
    runtime.status = "RUNNING"
    runtime.last_public = time.monotonic()
    runtime.manager = OrderManager(
        adapter,
        runtime.store,
        RiskEngine(),
        runtime.config,
        runtime.instrument,
        runtime.risk_context,
        runtime.notify,
    )
    try:
        for n in range(2):
            intent = OrderIntent(
                environment=Environment.DEMO,
                symbol="BTCUSDT",
                order_link_id=f"large-long-{n}",
                side=Side.LONG,
                qty=D("10"),
            )
            row = await runtime.manager.submit(intent)
            execution = await server.state.fill(row["order_id"])
            await runtime.manager.execution_event(execution)
            await runtime.manager.order_event(server.state.orders[row["order_id"]])
        await runtime.manager.ensure_protection()
        tp_ids = [r["order_id"] for r in await runtime.store.orders() if r["purpose"] == "TP"]
        assert len(tp_ids) == 2
        assert server.state.position_book[1]["qty"] == D("20")
        assert runtime.instrument.max_market_qty == D("10")
        server.state.market_auto_fill = True
        try:
            await runtime.close_all("CHIUDI TUTTO", True)
        except BotError:
            # Unsupported closure must fail before cancellation of protection.
            assert all(
                server.state.orders[order_id]["orderStatus"] == "New" for order_id in tp_ids
            ), "A size-limit failure cancelled protective TPs while the position remained open"
            assert server.state.position_book[1]["qty"] == D("20")
        else:
            assert server.state.position_book[1]["qty"] == 0
            closing = [r for r in await runtime.store.orders() if r["purpose"] == "CLOSE"]
            assert closing and all(
                D(r["qty"]) <= runtime.instrument.max_market_qty for r in closing
            )
    finally:
        await adapter.close()
        await runtime.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "idx,size,side", [(0, "0", "Buy"), (1, "1", "Buy"), (1, "NaN", "Buy"), (2, "1", "Buy")]
)
async def test_uncertain_position_websocket_frame_immediately_pauses_entries(
    tmp_path, idx, size, side
):
    from types import SimpleNamespace

    from gridbot.persistence import Store
    from gridbot.runtime import BotRuntime

    runtime = BotRuntime(tmp_path)
    runtime.store = Store(tmp_path / "position-integrity.sqlite")
    await runtime.store.initialize()
    runtime.manager = SimpleNamespace(uncertain=False)
    runtime.status = "RUNNING"
    runtime.connected = runtime.public_connected = runtime.private_connected = (
        runtime.reconciled
    ) = True
    try:
        await runtime.on_event(
            {
                "topic": "position",
                "data": [{"symbol": "BTCUSDT", "positionIdx": idx, "size": size, "side": side}],
            }
        )
        assert runtime.status == "DEGRADED"
        assert runtime.reconciled is False
        assert runtime.error
    finally:
        await runtime.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp_offset", [-1, 0])
async def test_out_of_order_or_duplicate_public_quote_cannot_replace_current_price(
    tmp_path, timestamp_offset
):
    from gridbot.persistence import Store
    from gridbot.runtime import BotRuntime

    runtime = BotRuntime(tmp_path)
    runtime.store = Store(tmp_path / "quote-ordering.sqlite")
    await runtime.store.initialize()
    runtime.status = "READY"
    runtime.connected = runtime.public_connected = runtime.private_connected = (
        runtime.reconciled
    ) = True
    try:
        timestamp = utc_ms()
        await runtime.on_event(
            {
                "topic": "tickers.BTCUSDT",
                "ts": timestamp,
                "data": {"symbol": "BTCUSDT", "lastPrice": "68000"},
            }
        )
        freshness = runtime.last_public
        await runtime.on_event(
            {
                "topic": "tickers.BTCUSDT",
                "ts": timestamp + timestamp_offset,
                "data": {"symbol": "BTCUSDT", "lastPrice": "67000"},
            }
        )
        assert runtime.price == D("68000")
        assert runtime.last_public == freshness
    finally:
        await runtime.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1", "0"])
async def test_invalid_public_quote_pauses_without_poisoning_last_valid_price(tmp_path, price):
    from gridbot.persistence import Store
    from gridbot.runtime import BotRuntime

    runtime = BotRuntime(tmp_path)
    runtime.store = Store(tmp_path / "quote-integrity.sqlite")
    await runtime.store.initialize()
    runtime.status = "READY"
    runtime.price = D("68000")
    runtime.connected = runtime.public_connected = runtime.private_connected = (
        runtime.reconciled
    ) = True
    try:
        await runtime.on_event(
            {
                "topic": "tickers.BTCUSDT",
                "ts": utc_ms(),
                "data": {"symbol": "BTCUSDT", "lastPrice": price},
            }
        )
        assert runtime.status == "DEGRADED"
        assert runtime.reconciled is False
        assert runtime.price == D("68000")
    finally:
        await runtime.store.close()


@pytest.mark.asyncio
async def test_funding_is_signed_deduplicated_persistent_and_counts_toward_daily_loss(
    local_bybit_server, tmp_path
):
    import time

    from gridbot.errors import RiskError
    from gridbot.models import Environment, OrderIntent, Side, StrategyConfig
    from gridbot.orders import OrderManager
    from gridbot.persistence import Store
    from gridbot.risk import RiskEngine
    from gridbot.runtime import BotRuntime

    server = local_bybit_server
    server.state.market_auto_fill = False
    adapter, transport = make_adapter(server)
    runtime = BotRuntime(tmp_path)
    path = tmp_path / "funding-ledger.sqlite"
    runtime.store = Store(path)
    await runtime.store.initialize()
    runtime.adapter = adapter
    runtime.account = await adapter.account()
    runtime.instrument = await adapter.instrument("BTCUSDT")
    await runtime._fetch_prices()
    runtime.config = StrategyConfig(max_daily_loss_usdt=D("2"))
    runtime.connected = runtime.public_connected = runtime.private_connected = (
        runtime.reconciled
    ) = True
    runtime.status = "RUNNING"
    runtime.last_public = time.monotonic()
    runtime.manager = OrderManager(
        adapter,
        runtime.store,
        RiskEngine(),
        runtime.config,
        runtime.instrument,
        runtime.risk_context,
        runtime.notify,
    )
    try:
        intent = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="funded-position",
            side=Side.LONG,
            qty=D("0.001"),
        )
        row = await runtime.manager.submit(intent)
        execution = await server.state.fill(row["order_id"])
        await runtime.manager.execution_event(execution)
        await runtime.manager.order_event(server.state.orders[row["order_id"]])
        paid = await server.state.settle_funding("Buy", D("-5"))
        await server.state.settle_funding("Buy", D("2"))
        server.state.transactions.append(dict(paid))  # repeated provider transaction
        await runtime._reconcile()
        events = await runtime.store.funding_events()
        assert len(events) == 2
        assert sum((D(e["amount"]) for e in events), D(0)) == D("-3")
        portfolio = await runtime.portfolio()
        assert D(portfolio["funding"]) == D("-3")
        assert D(portfolio["fees"]) == D("0.0402")
        assert D(portfolio["net"]) == D("-3.0402")
        assert D(portfolio["today"]) == D("-3.0402")
        proposed = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="loss-limit-must-block",
            side=Side.LONG,
            qty=D("0.001"),
        )
        with pytest.raises(RiskError, match="Max Daily Loss"):
            runtime.manager.risk.validate_order(
                proposed, await runtime.risk_context(proposed), runtime.config, runtime.instrument
            )
        await runtime._reconcile()
        assert len(await runtime.store.funding_events()) == 2
        assert any(
            url.startswith("https://api-demo.bybit.com/v5/account/transaction-log")
            for url in transport.requested_urls
        )
        await runtime.store.close()
        runtime.store = Store(path)
        await runtime.store.initialize()
        assert len(await runtime.store.funding_events()) == 2
        assert sum((D(e["amount"]) for e in await runtime.store.funding_events()), D(0)) == D("-3")
    finally:
        await adapter.close()
        await runtime.store.close()


@pytest.mark.asyncio
async def test_existing_trade_database_cannot_be_rebound_to_another_uid_after_restart(
    local_bybit_server, tmp_path
):
    """A different account with identical zero positions must not adopt an old ledger."""
    from gridbot.errors import BotError
    from gridbot.models import Environment, OrderIntent, Side, StrategyConfig
    from test_runtime import make_runtime, wait_for

    server = local_bybit_server
    first = make_runtime(tmp_path, server)
    await first.initialize()
    try:
        await first.connect(Environment.DEMO)
        await wait_for(lambda: first.public_connected and first.private_connected)
        await first.configure(StrategyConfig(initial_pair=False, levels=1))
        await first.start()
        for link, close in [("uid-entry", False), ("uid-close", True)]:
            intent = OrderIntent(
                environment=Environment.DEMO,
                symbol="BTCUSDT",
                order_link_id=link,
                side=Side.LONG,
                qty=D("0.001"),
                reduce_only=close,
                purpose="CLOSE" if close else "GRID",
                parent_link_id="uid-entry" if close else None,
            )
            await first.store.claim_intent(intent)
            acknowledgement = await first.adapter.create_order(intent)
            await first.manager.execution_event(server.state.executions[-1])
            await first.manager.order_event(server.state.orders[acknowledgement["orderId"]])
        assert await first.store.lots() == []
    finally:
        await first.shutdown()
    # Simulate switching API credentials to a second empty account: no old order
    # history, identical aggregate position quantities, and a distinct verified UID.
    server.state.uid = "999999"
    server.state.api_key = "second-local-simulator-key"
    server.state.api_secret = "second-local-simulator-secret"
    server.state.orders.clear()
    server.state.executions.clear()
    reopened = make_runtime(tmp_path, server)
    await reopened.initialize()
    try:
        with pytest.raises(BotError):
            await reopened.connect(Environment.DEMO)
        assert reopened.status == "DEGRADED"
        assert reopened.reconciled is False
        assert len(await reopened.store.executions()) == 2
    finally:
        await reopened.shutdown()


@pytest.mark.asyncio
async def test_definitively_rejected_zero_fill_injection_clears_recovery_preserving_original_tp(
    local_bybit_server, tmp_path
):
    import time

    from gridbot.errors import BotError
    from gridbot.models import Environment, OrderIntent, Side, StrategyConfig
    from gridbot.orders import OrderManager
    from gridbot.persistence import Store
    from gridbot.risk import RiskEngine
    from gridbot.runtime import BotRuntime

    server = local_bybit_server
    server.state.market_auto_fill = False
    adapter, _ = make_adapter(server)
    runtime = BotRuntime(tmp_path)
    runtime.store = Store(tmp_path / "rejected-recovery.sqlite")
    await runtime.store.initialize()
    runtime.adapter = adapter
    runtime.account = await adapter.account()
    runtime.instrument = await adapter.instrument("BTCUSDT")
    await runtime._fetch_prices()
    runtime.config = StrategyConfig(recovery_retrace_pct=D("2"))
    runtime.connected = runtime.public_connected = runtime.private_connected = (
        runtime.reconciled
    ) = True
    runtime.status = "RUNNING"
    runtime.last_public = time.monotonic()
    runtime.session_id = "qa-recovery-session"
    runtime.manager = OrderManager(
        adapter,
        runtime.store,
        RiskEngine(),
        runtime.config,
        runtime.instrument,
        runtime.risk_context,
        runtime.notify,
    )
    try:
        entry = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="recovery-existing-long",
            side=Side.LONG,
            qty=D("0.001"),
        )
        row = await runtime.manager.submit(entry)
        execution = await server.state.fill(row["order_id"])
        await runtime.manager.execution_event(execution)
        await runtime.manager.order_event(server.state.orders[row["order_id"]])
        await runtime.manager.ensure_protection()
        tp = next(r for r in await runtime.store.orders() if r["purpose"] == "TP")
        await server.state.advance_market(D("64000"))
        await runtime._fetch_prices()
        assert (await runtime.recovery_plans())[0]["safe"] is True
        server.state.reject_next_create = True
        with pytest.raises(BotError):
            await runtime.inject(Side.LONG, True)
        injection = next(r for r in await runtime.store.orders() if r["purpose"] == "RECOVERY")
        assert injection["state"] == "REJECTED" and D(injection["executed_qty"]) == 0
        assert "LONG" not in runtime.active_recovery
        persisted = await runtime.store.get("recovery_blocks", "active")
        assert "LONG" not in persisted["sides"]
        assert server.state.orders[tp["order_id"]]["orderStatus"] == "New"
        assert server.state.position_book[1]["qty"] == D("0.001")
        assert len(server.state.orders) == 2
        assert sum(call["path"] == "/v5/order/create" for call in server.state.calls) == 3
        await runtime._recovery_protection()  # rejected injection must not poison later monitoring
    finally:
        await adapter.close()
        await runtime.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mark_available", [True, False])
async def test_daily_loss_reconstructs_overnight_inventory_from_actual_midnight_mark(
    local_bybit_server, tmp_path, mark_available
):
    """Daily PnL is actual cash flow plus inventory mark change, including app downtime."""
    import time
    from types import SimpleNamespace

    from gridbot.errors import BotError, RiskError
    from gridbot.models import Environment, OrderIntent, Side, StrategyConfig
    from gridbot.persistence import Store
    from gridbot.risk import RiskEngine
    from gridbot.runtime import BotRuntime

    server = local_bybit_server
    server.state.midnight_mark = D("68000") if mark_available else None
    server.state.price = D("65000")
    adapter, transport = make_adapter(server)
    runtime = BotRuntime(tmp_path)
    runtime.store = Store(tmp_path / "overnight-ledger.sqlite")
    await runtime.store.initialize()
    runtime.adapter = adapter
    runtime.account = await adapter.account()
    runtime.instrument = await adapter.instrument("BTCUSDT")
    await runtime._fetch_prices()
    runtime.config = StrategyConfig(order_size_usdt=D("1000"), max_daily_loss_usdt=D("5"))
    runtime.manager = SimpleNamespace(uncertain=False)
    runtime.status = "RUNNING"
    runtime.connected = runtime.public_connected = runtime.private_connected = (
        runtime.reconciled
    ) = True
    runtime.last_public = time.monotonic()
    day = utc_ms() // 86400000 * 86400000
    try:
        # Yesterday buy10 units, yesterday sell4, today sell2 and buy3; quantities
        # are expressed in 0.001 BTC lots so the remaining overnight inventory is6.
        movements = [
            ("overnight-entry", "0.010", "67000", "0.402", day - 7200000, False, None),
            ("yesterday-close", "0.004", "68000", "0.1632", day - 3600000, True, "overnight-entry"),
            ("today-close", "0.002", "69000", "0.0828", day + 1, True, "overnight-entry"),
            ("today-entry", "0.003", "64000", "0.1152", day + 2, False, None),
        ]
        for link, qty, price, fee, timestamp, close, parent in movements:
            intent = OrderIntent(
                environment=Environment.DEMO,
                symbol="BTCUSDT",
                order_link_id=link,
                side=Side.LONG,
                qty=D(qty),
                reduce_only=close,
                purpose="TP" if close else "GRID",
                parent_link_id=parent,
            )
            await runtime.store.claim_intent(intent)
            payload = execution_payload("exec-" + link, link, qty, price, fee=fee, close=close)
            payload["execTime"] = str(timestamp)
            await runtime.store.apply_execution(payload)
        await runtime.store.apply_funding_transaction(
            {
                "id": "overnight-funding",
                "transactionTime": str(day + 3),
                "symbol": "BTCUSDT",
                "category": "linear",
                "currency": "USDT",
                "side": "Buy",
                "funding": "-0.5",
            }
        )
        if not mark_available:
            with pytest.raises(BotError):
                await runtime.portfolio()
            assert any("/v5/market/mark-price-kline" in url for url in transport.requested_urls)
        else:
            portfolio = await runtime.portfolio()
            # Closing inventory455 +sales138 -opening inventory408 -new buys192
            # -today fees0.198 -funding0.5 = -7.698. Lifetime net is positive.
            assert D(portfolio["today"]) == D("455") + D("138") - D("408") - D("192") - D(
                "0.198"
            ) - D("0.5")
            assert D(portfolio["net"]) == D("1.7368")
            proposed = OrderIntent(
                environment=Environment.DEMO,
                symbol="BTCUSDT",
                order_link_id="overnight-loss-must-block",
                side=Side.LONG,
                qty=D("0.001"),
            )
            with pytest.raises(RiskError, match="Max Daily Loss"):
                RiskEngine().validate_order(
                    proposed,
                    await runtime.risk_context(proposed),
                    runtime.config,
                    runtime.instrument,
                )
            midnight_calls = [
                c for c in server.state.calls if c["path"] == "/v5/market/mark-price-kline"
            ]
            assert midnight_calls and int(midnight_calls[0]["query"]["start"]) == day
    finally:
        await adapter.close()
        await runtime.store.close()
