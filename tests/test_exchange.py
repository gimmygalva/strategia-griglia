"""Transport-level contracts. All exchange responses here are local fixtures."""

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from gridbot.credentials import CredentialsStore, MemoryCredentialsStore
from gridbot.environments import EnvironmentValidation, endpoints_for
from gridbot.errors import (
    AuthenticationError,
    BybitAPIError,
    NetworkError,
    OrderNotSentError,
    RiskError,
    UncertainOrderError,
    ValidationError,
)
from gridbot.exchange import (
    AccountTypeError,
    BybitDemoAdapter,
    BybitMainnetAdapter,
    HedgeModeError,
    PermissionMissingError,
)
from gridbot.models import Credentials, Environment, OrderIntent, Side
from gridbot.persistence import Store
from mock_bybit import LoopbackTransport

pytestmark = pytest.mark.asyncio


def credentials(environment=Environment.DEMO):
    return Credentials(
        environment=environment, api_key="LOCAL_FIXTURE_KEY", api_secret="LOCAL_FIXTURE_SECRET"
    )


def reply(result=None, *, code=0, message="OK", status=200, headers=None):
    return httpx.Response(
        status,
        json={
            "retCode": code,
            "retMsg": message,
            "result": result or {},
            "time": int(time.time() * 1000),
        },
        headers=headers,
    )


def intent(environment=Environment.DEMO, side=Side.LONG, reduce_only=False, order_type="Market"):
    return OrderIntent(
        environment=environment,
        symbol="BTCUSDT",
        order_link_id="fixture-unique-order-1",
        side=side,
        qty=Decimal("0.001"),
        price=Decimal("67000.1") if order_type == "Limit" else None,
        order_type=order_type,
        reduce_only=reduce_only,
    )


async def test_demo_and_mainnet_endpoint_separation():
    demo, live = endpoints_for(Environment.DEMO), endpoints_for(Environment.MAINNET)
    assert demo.rest == "https://api-demo.bybit.com"
    assert demo.private_ws == "wss://stream-demo.bybit.com/v5/private"
    assert live.rest == "https://api.bybit.com"
    assert live.private_ws == "wss://stream.bybit.com/v5/private"
    assert demo.public_ws == live.public_ws == "wss://stream.bybit.com/v5/public/linear"
    assert demo.public_rest == live.public_rest == "https://api.bybit.com"
    assert demo.namespace != live.namespace
    assert "testnet" not in repr(demo).lower()
    with pytest.raises(ValidationError):
        EnvironmentValidation.validate(Environment.DEMO, credentials(Environment.MAINNET), demo)
    with pytest.raises(ValidationError):
        EnvironmentValidation.validate(
            Environment.DEMO, credentials(), replace(demo, rest=live.rest)
        )


async def test_adapter_parity_and_constructor_environment_rejection():
    for name in (
        "set_order_guard",
        "public_get",
        "private_get",
        "private_post",
        "instrument",
        "ticker",
        "midnight_mark",
        "candles",
        "account",
        "positions",
        "open_orders",
        "executions",
        "transactions",
        "find_order",
        "create_order",
        "cancel_order",
        "set_leverage",
        "close",
    ):
        assert getattr(BybitDemoAdapter, name) is getattr(BybitMainnetAdapter, name)
    with pytest.raises(ValidationError):
        BybitMainnetAdapter(credentials())
    with pytest.raises(ValidationError):
        BybitDemoAdapter(credentials(Environment.MAINNET))


async def test_get_signs_actual_percent_encoded_query_and_public_is_unsigned():
    seen = []

    async def handler(request):
        seen.append(request)
        if request.url.path == "/v5/order/realtime":
            assert request.url.host == "api-demo.bybit.com"
            raw = request.url.query.decode()
            signed = request.headers["X-BAPI-TIMESTAMP"] + "LOCAL_FIXTURE_KEY" + "5000" + raw
            expected = hmac.new(
                b"LOCAL_FIXTURE_SECRET", signed.encode(), hashlib.sha256
            ).hexdigest()
            assert request.headers["X-BAPI-SIGN"] == expected
            assert "cursor=a%2Bb%26c" in raw
        else:
            assert request.url.host == "api.bybit.com"
            assert "X-BAPI-API-KEY" not in request.headers
        return reply({"list": []})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        await adapter.private_get("/v5/order/realtime", {"cursor": "a+b&c", "symbol": "BTCUSDT"})
        await adapter.public_get("/v5/market/tickers", {"symbol": "BTCUSDT"})
        assert len(seen) == 2
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "side,reduce_only,expected_side,idx",
    [
        (Side.LONG, False, "Buy", 1),
        (Side.SHORT, False, "Sell", 2),
        (Side.LONG, True, "Sell", 1),
        (Side.SHORT, True, "Buy", 2),
    ],
)
async def test_orders_preserve_distinct_hedge_position_idx_and_signature(
    side, reduce_only, expected_side, idx
):
    async def handler(request):
        payload = json.loads(request.content)
        assert payload["side"] == expected_side and payload["positionIdx"] == idx
        assert payload["reduceOnly"] == reduce_only
        assert payload["qty"] == "0.001"
        assert (
            payload["slippageToleranceType"] == "Percent" and payload["slippageTolerance"] == "0.10"
        )
        signed = (
            request.headers["X-BAPI-TIMESTAMP"]
            + "LOCAL_FIXTURE_KEY"
            + "5000"
            + request.content.decode()
        )
        assert (
            request.headers["X-BAPI-SIGN"]
            == hmac.new(b"LOCAL_FIXTURE_SECRET", signed.encode(), hashlib.sha256).hexdigest()
        )
        return reply({"orderId": "exchange-order-fixture", "orderLinkId": payload["orderLinkId"]})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        acknowledgement = await adapter.create_order(intent(side=side, reduce_only=reduce_only))
        assert acknowledgement == {
            "orderId": "exchange-order-fixture",
            "orderLinkId": "fixture-unique-order-1",
        }
        assert "status" not in acknowledgement  # ACK is never execution confirmation.
    finally:
        await adapter.close()


async def test_take_profit_limit_order_uses_real_price_and_no_attached_position_tp():
    async def handler(request):
        payload = json.loads(request.content)
        assert payload["orderType"] == "Limit" and payload["price"] == "67000.1"
        assert payload["reduceOnly"] is True and payload["timeInForce"] == "GTC"
        assert "takeProfit" not in payload and "slippageToleranceType" not in payload
        return reply({"orderId": "fixture-tp", "orderLinkId": payload["orderLinkId"]})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        await adapter.create_order(intent(reduce_only=True, order_type="Limit"))
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "failure", ["timeout", "disconnect", "http500", "invalid_json", "missing_ack"]
)
async def test_mutations_are_not_blindly_retried_on_uncertain_response(failure):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("local fixture timeout", request=request)
        if failure == "disconnect":
            raise httpx.ConnectError("local fixture disconnect", request=request)
        if failure == "http500":
            return reply(status=500)
        if failure == "invalid_json":
            return httpx.Response(200, text="not-json")
        return reply({"orderId": "fixture-order"})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(UncertainOrderError):
            await adapter.create_order(intent())
        assert calls == 1
    finally:
        await adapter.close()


async def test_safe_get_retries_429_rate_headers_and_server_error_with_backoff():
    calls, delays = 0, []

    async def delay(value):
        delays.append(value)

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return reply(status=429, headers={"Retry-After": "1.5"})
        if calls == 2:
            return reply(status=503)
        return reply({"list": []})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler), sleep=delay)
    try:
        assert await adapter.open_orders("BTCUSDT") == []
        assert calls == 3 and len(delays) == 2
        assert delays[0] >= 1.5 and delays[1] >= 1
    finally:
        await adapter.close()


async def test_get_failures_exhaust_bounded_retry_budget():
    calls, delays = 0, []

    async def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("local timeout", request=request)

    async def delay(value):
        delays.append(value)

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler), sleep=delay)
    try:
        with pytest.raises(NetworkError):
            await adapter.open_orders("BTCUSDT")
        assert calls == 4 and len(delays) == 3
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "code,error",
    [
        (10003, AuthenticationError),
        (10004, AuthenticationError),
        (10005, PermissionMissingError),
        (110007, BybitAPIError),
    ],
)
async def test_exchange_error_messages_do_not_echo_secrets_or_request_body(code, error, caplog):
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(
            lambda request: reply(
                code=code,
                message="LOCAL_FIXTURE_KEY LOCAL_FIXTURE_SECRET <script>alert(1)</script>",
            )
        ),
    )
    try:
        with pytest.raises(error) as captured:
            await adapter.private_get("/v5/account/info", {})
        assert "LOCAL_FIXTURE" not in str(captured.value)
        assert "LOCAL_FIXTURE_SECRET" not in caplog.text
        assert "<script>" not in str(captured.value)
    finally:
        await adapter.close()


@pytest.mark.parametrize("allowed,confirmed", [(False, False), (True, False), (False, True)])
async def test_mainnet_mutations_default_disabled_and_require_both_gates(allowed, confirmed):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return reply()

    adapter = BybitMainnetAdapter(
        credentials(Environment.MAINNET),
        mainnet_allowed=allowed,
        live_confirmed=confirmed,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RiskError):
            await adapter.create_order(intent(environment=Environment.MAINNET))
        with pytest.raises(RiskError):
            await adapter.cancel_order("BTCUSDT", "fixture-order", "fixture-link")
        assert calls == 0
        assert (
            await adapter.private_get("/v5/account/info", {}) == {}
        )  # Read-only validation allowed.
        assert calls == 1
    finally:
        await adapter.close()


async def test_mismatched_order_environment_and_modified_endpoints_block_before_network():
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(lambda request: pytest.fail("network must not be called")),
    )
    try:
        with pytest.raises(ValidationError):
            await adapter.create_order(intent(environment=Environment.MAINNET))
        adapter.endpoints = endpoints_for(Environment.MAINNET)
        with pytest.raises(ValidationError):
            await adapter.private_get("/v5/account/info", {})
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example/v5/account/info",
        "/v5/../account/info",
        "/v5/order/create?key=stolen",
        "/v5//account/info",
        "/v5/account/info#fragment",
    ],
)
async def test_path_injection_rejected_without_signed_request(path):
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(lambda request: pytest.fail("network must not be called")),
    )
    try:
        with pytest.raises(ValidationError):
            await adapter.private_get(path, {})
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "method,path,limit",
    [
        ("open_orders", "/v5/order/realtime", "50"),
        ("positions", "/v5/position/list", "200"),
        ("executions", "/v5/execution/list", "100"),
    ],
)
async def test_all_private_lists_paginate_beyond_first_page(method, path, limit):
    seen = []
    rows = (
        [{"page": page, "execId": f"page-{page}", "execTime": str(page)} for page in (1, 2)]
        if method == "executions"
        else [{"page": 1}, {"page": 2}]
    )

    async def handler(request):
        assert request.url.path == path and request.url.params["limit"] == limit
        seen.append(request.url.params.get("cursor"))
        page = 2 if request.url.params.get("cursor") else 1
        return reply({"list": [rows[page - 1]], "nextPageCursor": "cursor+2" if page == 1 else ""})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        assert await getattr(adapter, method)("BTCUSDT") == rows
        assert seen == [None, "cursor+2"]
    finally:
        await adapter.close()


async def test_repeated_pagination_cursor_blocks_inconsistent_reconciliation():
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(
            lambda request: reply({"list": [], "nextPageCursor": "same-cursor"})
        ),
    )
    try:
        with pytest.raises(ValidationError, match="Paginazione"):
            await adapter.open_orders("BTCUSDT")
    finally:
        await adapter.close()


async def test_find_order_reads_history_if_realtime_cache_was_lost_after_exchange_restart():
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        return reply(
            {
                "list": []
                if request.url.path.endswith("realtime")
                else [
                    {
                        "orderId": "fixture-existing",
                        "orderLinkId": "fixture-restart",
                        "orderStatus": "Filled",
                        "updatedTime": "2",
                    }
                ]
            }
        )

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        order = await adapter.find_order("BTCUSDT", "fixture-restart")
        assert order["orderId"] == "fixture-existing"
        assert paths == ["/v5/order/realtime", "/v5/order/history"]
    finally:
        await adapter.close()


def account_fixture(path, overrides=None):
    defaults = {
        "/v5/market/time": {"timeNano": str(time.time_ns())},
        "/v5/user/query-api": {
            "apiKey": "LOCAL_FIXTURE_KEY",
            "userID": "123456",
            "readOnly": 0,
            "permissions": {"ContractTrade": ["Order", "Position"]},
        },
        "/v5/account/info": {"unifiedMarginStatus": 5, "marginMode": "REGULAR_MARGIN"},
        "/v5/account/wallet-balance": {
            "list": [
                {
                    "accountType": "UNIFIED",
                    "totalEquity": "1500",
                    "totalAvailableBalance": "1200",
                    "coin": [{"coin": "USDT", "walletBalance": "1000", "spotBorrow": "20"}],
                }
            ]
        },
        "/v5/position/list": {
            "list": [
                {"symbol": "BTCUSDT", "positionIdx": 1, "leverage": "1", "size": "0"},
                {"symbol": "BTCUSDT", "positionIdx": 2, "leverage": "1", "size": "0"},
            ]
        },
        "/v5/account/fee-rate": {
            "list": [{"symbol": "BTCUSDT", "makerFeeRate": "0.0002", "takerFeeRate": "0.00055"}]
        },
    }
    if overrides:
        defaults.update(overrides)
    return defaults[path]


async def test_account_validates_uid_uta_permissions_hedge_and_conservative_cash_balance():
    paths = []

    async def handler(request):
        paths.append((request.url.host, request.url.path))
        return reply(account_fixture(request.url.path))

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        account = await adapter.account()
        assert (
            account.uid == "123456"
            and account.uta_status == 5
            and account.hedge_mode
            and account.permissions
        )
        assert account.equity == Decimal("1500")
        assert account.available_balance == Decimal(
            "980"
        )  # Cannot borrow against equity or collateral.
        assert account.taker_fee == Decimal("0.00055") and account.maker_fee == Decimal("0.0002")
        assert account.fee_source == "Bybit account fee-rate API"
        assert all(
            host == "api-demo.bybit.com"
            for host, path in paths
            if not path.startswith("/v5/market/")
        )
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "override,error",
    [
        (
            {
                "/v5/user/query-api": {
                    "userID": "1",
                    "readOnly": 1,
                    "permissions": {"ContractTrade": ["Order", "Position"]},
                }
            },
            PermissionMissingError,
        ),
        (
            {
                "/v5/user/query-api": {
                    "userID": "1",
                    "readOnly": 0,
                    "permissions": {"ContractTrade": ["Order"]},
                }
            },
            PermissionMissingError,
        ),
        (
            {"/v5/account/info": {"unifiedMarginStatus": 1, "marginMode": "REGULAR_MARGIN"}},
            AccountTypeError,
        ),
        (
            {"/v5/account/info": {"unifiedMarginStatus": 5, "marginMode": "PORTFOLIO_MARGIN"}},
            AccountTypeError,
        ),
        (
            {
                "/v5/position/list": {
                    "list": [{"symbol": "BTCUSDT", "positionIdx": 0, "leverage": "1", "size": "0"}]
                }
            },
            HedgeModeError,
        ),
        (
            {
                "/v5/user/query-api": {
                    "apiKey": "DIFFERENT_KEY",
                    "userID": "1",
                    "readOnly": 0,
                    "permissions": {"ContractTrade": ["Order", "Position"]},
                }
            },
            AuthenticationError,
        ),
    ],
)
async def test_incompatible_account_blocks_trading_without_mutating_hedge_mode(override, error):
    async def handler(request):
        assert request.method == "GET"
        return reply(account_fixture(request.url.path, override))

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(error):
            await adapter.account()
    finally:
        await adapter.close()


async def test_unavailable_demo_permission_probe_fails_closed_not_assumed_true():
    async def handler(request):
        if request.url.path == "/v5/user/query-api":
            return reply(code=10017)
        return reply(account_fixture(request.url.path))

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(BybitAPIError) as error:
            await adapter.account()
        assert error.value.ret_code == 10017
    finally:
        await adapter.close()


async def test_demo_missing_fee_endpoint_is_explicit_estimate_not_fabricated_exchange_fee():
    async def handler(request):
        if request.url.path == "/v5/account/fee-rate":
            return reply(status=404)
        return reply(account_fixture(request.url.path))

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        account = await adapter.account()
        assert "estimate" in account.fee_source.lower()
        assert account.taker_fee == Decimal("0.0006")
    finally:
        await adapter.close()


async def test_existing_positions_prevent_implicit_leverage_changes():
    async def handler(request):
        assert request.method == "GET"
        return reply(
            {
                "list": [
                    {"symbol": "BTCUSDT", "positionIdx": 1, "leverage": "2", "size": "0.004"},
                    {"symbol": "BTCUSDT", "positionIdx": 2, "leverage": "2", "size": "0"},
                ]
            }
        )

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RiskError, match="posizioni"):
            await adapter.set_leverage("BTCUSDT", Decimal("1"))
    finally:
        await adapter.close()


async def test_candles_sorted_and_decimals_are_not_floats():
    rows = [
        ["2000", "1.01", "1.03", "1.00", "1.02", "42"],
        ["1000", "1.00", "1.01", "0.99", "1.01", "30"],
    ]
    adapter = BybitDemoAdapter(
        credentials(), transport=httpx.MockTransport(lambda request: reply({"list": rows}))
    )
    try:
        candles = await adapter.candles("BTCUSDT")
        assert [row["time"] for row in candles] == [1, 2]
        assert candles[0]["open"] == "1.00"
    finally:
        await adapter.close()


async def test_credential_store_separates_namespaces_and_secret_repr_is_masked():
    store = MemoryCredentialsStore()
    store.save(credentials())
    assert store.load(Environment.MAINNET) is None
    assert store.load(Environment.DEMO).api_secret.get_secret_value() == "LOCAL_FIXTURE_SECRET"
    assert "LOCAL_FIXTURE_SECRET" not in repr(store.load(Environment.DEMO))
    assert not store.persistent
    store.delete(Environment.DEMO)
    assert store.load(Environment.DEMO) is None


async def test_keychain_failure_cannot_fallback_to_plaintext_or_memory():
    class BrokenKeychain:
        def set_password(self, service, user, password):
            raise RuntimeError("secret internal fixture")

    store = CredentialsStore(keychain_backend=BrokenKeychain())
    with pytest.raises(ValidationError, match="Keychain"):
        store.save(credentials())
    assert store.persistent and store._memory == {}


@pytest.mark.parametrize("code", [10000, 10014, 10016, 110072])
async def test_exchange_server_timeout_and_duplicate_id_require_reconciliation(code):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return reply(code=code)

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(UncertainOrderError):
            await adapter.create_order(intent())
        assert calls == 1
    finally:
        await adapter.close()


@pytest.mark.parametrize("code", [0.1, False, {}, "invalid"])
async def test_invalid_response_code_never_counts_as_mutation_acknowledgement(code):
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(
            lambda request: reply(
                {"orderId": "fixture", "orderLinkId": "fixture-unique-order-1"}, code=code
            )
        ),
    )
    try:
        with pytest.raises(UncertainOrderError):
            await adapter.create_order(intent())
    finally:
        await adapter.close()


async def test_mainnet_authorized_local_fixture_payload_matches_demo_except_private_domain():
    payloads, hosts = [], []

    async def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        hosts.append(request.url.host)
        return reply({"orderId": "local-fixture", "orderLinkId": payload["orderLinkId"]})

    demo = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    live = BybitMainnetAdapter(
        credentials(Environment.MAINNET),
        mainnet_allowed=True,
        live_confirmed=True,
        transport=httpx.MockTransport(handler),
    )
    try:
        await demo.create_order(intent())
        await live.create_order(intent(environment=Environment.MAINNET))
        assert payloads[0] == payloads[1]
        assert hosts == ["api-demo.bybit.com", "api.bybit.com"]
    finally:
        await demo.close()
        await live.close()


async def test_instrument_uses_live_exchange_filters_in_decimal_without_defaulting_missing_rules():
    row = {
        "symbol": "BTCUSDT",
        "contractType": "LinearPerpetual",
        "settleCoin": "USDT",
        "status": "Trading",
        "unifiedMarginTrade": True,
        "priceFilter": {"tickSize": "0.10"},
        "lotSizeFilter": {
            "minNotionalValue": "5",
            "maxOrderQty": "100",
            "maxMktOrderQty": "50",
            "minOrderQty": "0.001",
            "qtyStep": "0.001",
        },
        "leverageFilter": {"minLeverage": "1", "maxLeverage": "100"},
    }
    adapter = BybitDemoAdapter(
        credentials(), transport=httpx.MockTransport(lambda request: reply({"list": [row]}))
    )
    try:
        instrument = await adapter.instrument("BTCUSDT")
        assert instrument.tick_size == Decimal("0.10") and instrument.qty_step == Decimal("0.001")
        assert instrument.min_notional == Decimal("5") and instrument.max_market_qty == Decimal(
            "50"
        )
        del row["lotSizeFilter"]["minNotionalValue"]
        with pytest.raises(ValidationError, match="incomplete"):
            await adapter.instrument("BTCUSDT")
    finally:
        await adapter.close()


async def test_execution_history_splits_seven_day_windows_and_deduplicates_execution_ids():
    now = int(time.time() * 1000)
    start = now - 11 * 86400000
    windows = []

    async def handler(request):
        first = int(request.url.params["startTime"])
        last = int(request.url.params["endTime"]) if "endTime" in request.url.params else None
        if last is not None:
            assert last - first < 7 * 86400000
        else:
            assert first + 7 * 86400000 > int(time.time() * 1000)
        windows.append((first, last))
        return reply(
            {
                "list": [
                    {"execId": "duplicate-fixture-e1", "execTime": str(start), "execQty": "4"},
                    {"execId": f"window-{len(windows)}", "execTime": str(first), "execQty": "1"},
                ]
            }
        )

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        executions = await adapter.executions("BTCUSDT", start_time=start)
        assert len(windows) == 3 and windows[-1][1] is None
        assert windows[0] == (start, start + 7 * 86400000 - 1)
        assert all(
            right[0] == left[1] + 1 for left, right in zip(windows[:-1], windows[1:], strict=True)
        )
        assert len(executions) == 4
    finally:
        await adapter.close()


@pytest.mark.parametrize("field,changed", [("execQty", "0.002"), ("execPrice", "68000.1")])
@pytest.mark.parametrize("scope", ["pages", "windows"])
async def test_conflicting_rest_execution_evidence_blocks_reconciliation(field, changed, scope):
    first_row = {
        "execId": "conflicting-provider-execution",
        "execTime": "12345",
        "execQty": "0.001",
        "execPrice": "67000.1",
        "orderId": "provider-order",
    }
    queries = []

    async def handler(request):
        queries.append(dict(request.url.params))
        row = first_row if len(queries) == 1 else {**first_row, field: changed}
        return reply(
            {
                "list": [row],
                "nextPageCursor": "second-page" if scope == "pages" and len(queries) == 1 else "",
            }
        )

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        start = int(time.time() * 1000) - 11 * 86400000 if scope == "windows" else None
        with pytest.raises(ValidationError, match="duplicata con dati incoerenti"):
            await adapter.executions("BTCUSDT", start_time=start)
        assert len(queries) == 2
        if scope == "pages":
            assert "cursor" not in queries[0] and queries[1]["cursor"] == "second-page"
        else:
            assert all("cursor" not in query for query in queries)
            assert int(queries[1]["startTime"]) == int(queries[0]["endTime"]) + 1
    finally:
        await adapter.close()


async def test_identical_rest_execution_evidence_across_default_pages_is_idempotent():
    row = {"execId": "same-provider-execution", "execTime": "12345", "execQty": "0.001"}
    cursors = []

    async def handler(request):
        cursors.append(request.url.params.get("cursor"))
        return reply({"list": [row], "nextPageCursor": "page-two" if len(cursors) == 1 else ""})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        assert await adapter.executions("BTCUSDT") == [row]
        assert cursors == [None, "page-two"]
    finally:
        await adapter.close()


@pytest.mark.parametrize("historical", [False, True])
async def test_execution_queries_request_normal_trades_without_applying_cash_movements_as_fills(
    historical, tmp_path
):
    timestamp = int(time.time() * 1000)
    entry = intent()
    trade = {
        "execId": "normal-provider-fill",
        "orderId": "normal-provider-order",
        "orderLinkId": entry.order_link_id,
        "symbol": "BTCUSDT",
        "side": "Buy",
        "execType": "Trade",
        "execTime": str(timestamp),
        "execQty": "0.001",
        "execPrice": "67000.1",
        "execFee": "0.04",
    }
    movements = [
        {
            "execType": execution_type,
            "orderLinkId": entry.order_link_id,
            "execTime": str(timestamp),
            "execQty": "10",
            "execFee": "5",
        }
        for execution_type in ("Funding", "Delivery", "Settle")
    ]  # Non-trade cash evidence intentionally has no trade execution/order ID.
    queries = []

    async def handler(request):
        query = dict(request.url.params)
        queries.append(query)
        assert query["category"] == "linear" and query["execType"] == "Trade"
        first = int(query.get("startTime", timestamp - 7 * 86400000))
        last = int(query.get("endTime", first + 7 * 86400000))
        eligible = [
            row
            for row in [trade, *movements]
            if row["execType"] == query["execType"] and first <= int(row["execTime"]) <= last
        ]
        return reply({"list": eligible})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    store = Store(tmp_path / "normal-trades.sqlite")
    await store.initialize()
    try:
        await store.claim_intent(entry)
        start = timestamp - 11 * 86400000 if historical else None
        rows = await adapter.executions("BTCUSDT", start_time=start)
        assert rows == [trade]
        for row in rows:
            assert await store.apply_execution(row)
        assert len(await store.executions()) == 1
        assert Decimal((await store.lots())[0]["qty"]) == entry.qty
        assert Decimal((await store.get_order(entry.order_link_id))["executed_qty"]) == entry.qty
        assert len(queries) == (3 if historical else 1)
        assert all(query["execType"] == "Trade" for query in queries)
    finally:
        await adapter.close()
        await store.close()


@pytest.mark.parametrize("invalid_id", [None, "", True, 123, {}, [], "x" * 257, " ", "bad\nid"])
@pytest.mark.parametrize("historical", [False, True])
async def test_invalid_rest_execution_id_shape_blocks_reconciliation(invalid_id, historical):
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(
            lambda request: reply({"list": [{"execId": invalid_id, "execTime": "12345"}]})
        ),
    )
    try:
        start = int(time.time() * 1000) - 60000 if historical else None
        with pytest.raises(ValidationError, match="ID valido"):
            await adapter.executions("BTCUSDT", start_time=start)
    finally:
        await adapter.close()


def transaction_record(identifier, *, symbol="BTCUSDT", amount="-1.25", timestamp="12345"):
    return {
        "id": identifier,
        "symbol": symbol,
        "category": "linear",
        "currency": "USDT",
        "side": "Buy",
        "type": "SETTLEMENT",
        "transactionTime": timestamp,
        "funding": amount,
        "cashFlow": "0",
        "fee": "0",
        "change": amount,
        "qty": "10",
        "size": "10",
    }


async def test_funding_transaction_pagination_preserves_signed_funding_and_does_not_use_qty_as_fill():
    queries = []

    async def handler(request):
        assert request.url.path == "/v5/account/transaction-log"
        assert "symbol" not in request.url.params
        assert (
            request.url.params["category"] == "linear" and request.url.params["currency"] == "USDT"
        )
        queries.append(dict(request.url.params))
        if "cursor" not in request.url.params:
            return reply(
                {
                    "list": [
                        transaction_record("paid"),
                        transaction_record("other", symbol="ETHUSDT"),
                    ],
                    "nextPageCursor": "page2",
                }
            )
        return reply(
            {
                "list": [
                    transaction_record("paid"),
                    transaction_record("received", amount="2.50", timestamp="12346"),
                ]
            }
        )

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        transactions = await adapter.transactions("BTCUSDT")
        assert [row["id"] for row in transactions] == ["paid", "received"]
        assert transactions[0]["funding"] == "-1.25" and transactions[1]["funding"] == "2.50"
        assert transactions[0]["cashFlow"] == "0" and transactions[0]["qty"] == "10"
        assert len(queries) == 2
    finally:
        await adapter.close()


async def test_funding_history_splits_windows_and_uses_transaction_id_idempotence():
    start = int(time.time() * 1000) - 11 * 86400000
    windows = []

    async def handler(request):
        first = int(request.url.params["startTime"])
        last = int(request.url.params["endTime"]) if "endTime" in request.url.params else None
        windows.append((first, last))
        if last is not None:
            assert last - first < 7 * 86400000
        else:
            assert first + 24 * 3600000 > int(time.time() * 1000)
        return reply({"list": [transaction_record("repeated-id", timestamp=str(start))]})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        rows = await adapter.transactions("BTCUSDT", start_time=start)
        assert len(windows) == 3 and len(rows) == 1 and windows[-1][1] is None
        assert windows[0] == (start, start + 7 * 86400000 - 1)
        assert all(
            right[0] == left[1] + 1 for left, right in zip(windows[:-1], windows[1:], strict=True)
        )
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "ledger,implicit_span_ms,start_age_ms",
    [
        ("transactions", 86400000, age)
        for age in (60000, 12 * 3600000, 86400000 - 1, 86400000, 86400000 + 1, 11 * 86400000)
    ]
    + [
        ("executions", 7 * 86400000, age)
        for age in (60000, 3 * 86400000, 7 * 86400000 - 1, 7 * 86400000, 7 * 86400000 + 1)
    ],
)
async def test_history_tail_uses_documented_server_default_with_clock_headroom_and_pagination(
    monkeypatch, ledger, implicit_span_ms, start_age_ms
):
    server_now = int(time.time() * 1000)
    monkeypatch.setattr("gridbot.exchange.time.time", lambda: server_now / 1000)
    start = server_now - start_age_ms
    windows = []
    cursor_requests = []
    if ledger == "transactions":
        records = [
            transaction_record("historical", timestamp=str(start + 1)),
            transaction_record("latest", timestamp=str(server_now)),
        ]
        timestamp_field = "transactionTime"
    else:
        records = [
            {"execId": "historical", "execTime": str(start + 1)},
            {"execId": "latest", "execTime": str(server_now)},
        ]
        timestamp_field = "execTime"

    async def handler(request):
        first = int(request.url.params["startTime"])
        explicit_end = request.url.params.get("endTime")
        last = int(explicit_end) if explicit_end is not None else first + implicit_span_ms
        if explicit_end is not None:
            assert last - first < 7 * 86400000
        else:
            # This models the documented endpoint-specific implicit upper bound.
            assert first < server_now < last
        if "cursor" not in request.url.params:
            windows.append((first, int(explicit_end) if explicit_end is not None else None))
        else:
            cursor_requests.append(dict(request.url.params))
        eligible = [row for row in records if first <= int(row[timestamp_field]) <= last]
        if "cursor" in request.url.params:
            return reply({"list": eligible[1:]})
        return reply({"list": eligible[:1], "nextPageCursor": "page2" if len(eligible) > 1 else ""})

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    adapter.clock_offset_ms = -1000
    try:
        rows = await getattr(adapter, ledger)("BTCUSDT", start_time=start)
        id_field = "id" if ledger == "transactions" else "execId"
        assert [row[id_field] for row in rows] == ["historical", "latest"]
        assert windows[0][0] == start and windows[-1][1] is None
        assert all(
            right[0] == left[1] + 1 for left, right in zip(windows[:-1], windows[1:], strict=True)
        )
        if start_age_ms == 60000:
            assert len(cursor_requests) == 1 and "endTime" not in cursor_requests[0]
    finally:
        await adapter.close()


async def test_actual_loopback_history_recovers_latest_funding_and_fill_with_negative_clock(
    local_bybit_server,
):
    server = local_bybit_server
    server.state.market_auto_fill = False
    transport = LoopbackTransport(server)
    adapter = BybitDemoAdapter(
        Credentials(
            environment=Environment.DEMO,
            api_key=server.state.api_key,
            api_secret=server.state.api_secret,
        ),
        transport=transport,
    )
    adapter.clock_offset_ms = -1000
    try:
        acknowledged = await adapter.create_order(intent())
        execution = await server.state.fill(acknowledged["orderId"])
        funding = await server.state.settle_funding("Buy", Decimal("-1.25"))
        inferred_now = int(time.time() * 1000) + adapter.clock_offset_ms
        assert int(execution["execTime"]) > inferred_now
        assert int(funding["transactionTime"]) > inferred_now
        start = inferred_now - 11 * 86400000
        executions, transactions = await asyncio.gather(
            adapter.executions("BTCUSDT", start_time=start),
            adapter.transactions("BTCUSDT", start_time=start),
        )
        assert [row["execId"] for row in executions] == [execution["execId"]]
        assert [row["id"] for row in transactions] == [funding["id"]]
        assert transactions[0]["funding"] == "-1.25"
        for endpoint, implicit_span in (
            ("/v5/execution/list", 7 * 86400000),
            ("/v5/account/transaction-log", 86400000),
        ):
            queries = [call["query"] for call in server.state.calls if call["path"] == endpoint]
            assert len(queries) == 3
            assert "endTime" not in queries[-1]
            assert int(queries[-1]["startTime"]) + implicit_span > int(time.time() * 1000)
            assert int(queries[0]["endTime"]) == start + 7 * 86400000 - 1
            assert all(
                int(right["startTime"]) == int(left["endTime"]) + 1
                for left, right in zip(queries[:-1], queries[1:], strict=True)
            )
    finally:
        await adapter.close()


async def test_conflicting_funding_transaction_ids_block_accounting():
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(
            lambda request: reply(
                {
                    "list": [
                        transaction_record("same", amount="-1"),
                        transaction_record("same", amount="1"),
                    ]
                }
            )
        ),
    )
    try:
        with pytest.raises(ValidationError, match="incoerenti"):
            await adapter.transactions("BTCUSDT")
    finally:
        await adapter.close()


async def test_unavailable_funding_history_is_not_interpreted_as_zero_funding():
    adapter = BybitDemoAdapter(
        credentials(), transport=httpx.MockTransport(lambda request: reply(status=404))
    )
    try:
        with pytest.raises(BybitAPIError) as error:
            await adapter.transactions("BTCUSDT")
        assert error.value.ret_code == 10017
    finally:
        await adapter.close()


async def test_midnight_mark_fetches_exact_utc_open_from_real_mark_price_endpoint():
    day = int(time.time() * 1000) // 86400000 * 86400000

    async def handler(request):
        assert (
            request.url.host == "api.bybit.com"
            and request.url.path == "/v5/market/mark-price-kline"
        )
        assert dict(request.url.params) == {
            "category": "linear",
            "symbol": "BTCUSDT",
            "interval": "1",
            "start": str(day),
            "end": str(day + 59999),
            "limit": "1",
        }
        assert "X-BAPI-API-KEY" not in request.headers
        return reply(
            {
                "category": "linear",
                "symbol": "BTCUSDT",
                "list": [[str(day), "67000.10", "67001", "66999", "67000.30"]],
            }
        )

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        assert await adapter.midnight_mark("BTCUSDT", day) == Decimal("67000.10")
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "failure", ["missing", "wrong_timestamp", "wrong_symbol", "invalid_geometry"]
)
async def test_unverifiable_midnight_mark_never_falls_back_to_current_quote(failure):
    day = int(time.time() * 1000) // 86400000 * 86400000
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        result = {
            "category": "linear",
            "symbol": "BTCUSDT",
            "list": [[str(day), "67000", "67001", "66999", "67000"]],
        }
        if failure == "missing":
            result["list"] = []
        elif failure == "wrong_timestamp":
            result["list"][0][0] = str(day + 60000)
        elif failure == "wrong_symbol":
            result["symbol"] = "ETHUSDT"
        else:
            result["list"][0][2] = "1"
        return reply(result)

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValidationError):
            await adapter.midnight_mark("BTCUSDT", day)
        assert paths == ["/v5/market/mark-price-kline"]
    finally:
        await adapter.close()


async def test_midnight_mark_rejects_non_midnight_or_future_baseline():
    day = int(time.time() * 1000) // 86400000 * 86400000
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(lambda request: pytest.fail("no network on invalid day")),
    )
    try:
        for invalid in (day + 1, day + 86400000, -1, True):
            with pytest.raises(ValidationError):
                await adapter.midnight_mark("BTCUSDT", invalid)
    finally:
        await adapter.close()


@pytest.mark.parametrize("allowed,confirmed", [(False, True), (True, False)])
async def test_live_authorization_revoked_while_request_queued_blocks_before_send(
    allowed, confirmed
):
    adapter = BybitMainnetAdapter(
        credentials(Environment.MAINNET),
        mainnet_allowed=True,
        live_confirmed=True,
        transport=httpx.MockTransport(
            lambda request: pytest.fail("revoked LIVE request must not reach exchange")
        ),
    )
    adapter._semaphore = asyncio.Semaphore(0)
    task = asyncio.create_task(adapter.create_order(intent(environment=Environment.MAINNET)))
    try:
        await asyncio.sleep(0)
        assert not task.done()
        adapter.set_live_authorization(allowed, confirmed)
        adapter._semaphore.release()
        with pytest.raises(RiskError):
            await asyncio.wait_for(task, timeout=1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await adapter.close()


@pytest.mark.parametrize("environment", [Environment.DEMO, Environment.MAINNET])
async def test_order_guard_rechecks_revoked_state_after_semaphore_queue_before_send(environment):
    calls, checked = [], []
    safe = True

    async def handler(request):
        payload = json.loads(request.content)
        calls.append(payload["orderLinkId"])
        return reply({"orderId": "fixture-guard-approved", "orderLinkId": payload["orderLinkId"]})

    def guard(order):
        checked.append(order)
        if not safe:
            raise RiskError("Feed privato scollegato o prezzo scaduto")

    adapter_cls = BybitDemoAdapter if environment == Environment.DEMO else BybitMainnetAdapter
    adapter = adapter_cls(
        credentials(environment),
        mainnet_allowed=True,
        live_confirmed=True,
        transport=httpx.MockTransport(handler),
    )
    adapter.set_order_guard(guard)
    adapter._semaphore = asyncio.Semaphore(0)
    blocked = intent(environment=environment).model_copy(
        update={"purpose": "RECOVERY", "pair_id": "recovery-pair-fixture"}
    )
    task = asyncio.create_task(adapter.create_order(blocked))
    try:
        await asyncio.sleep(0)
        assert not task.done() and not checked and not calls
        safe = False
        adapter._semaphore.release()
        with pytest.raises(OrderNotSentError, match="Feed privato") as error:
            await asyncio.wait_for(task, timeout=1)
        assert not isinstance(error.value, UncertainOrderError)
        assert checked == [blocked] and checked[0].purpose == "RECOVERY"
        assert checked[0].pair_id == "recovery-pair-fixture" and calls == []
        safe = True
        approved = blocked.model_copy(update={"order_link_id": "guard-approved-other-link"})
        assert (await adapter.create_order(approved))["orderLinkId"] == approved.order_link_id
        assert calls == [approved.order_link_id]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await adapter.close()


async def test_installed_order_guard_cannot_be_bypassed_with_raw_private_post_create():
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(
            lambda request: pytest.fail("raw create bypass must not reach transport")
        ),
    )
    checked = []
    adapter.set_order_guard(lambda order: checked.append(order))
    try:
        with pytest.raises(OrderNotSentError, match="intenzione completa"):
            await adapter.private_post(
                "/v5/order/create",
                {"symbol": "BTCUSDT", "qty": "0.001", "orderLinkId": "raw-bypass"},
            )
        assert checked == []
    finally:
        await adapter.close()


async def test_guard_installed_while_raw_create_is_queued_also_blocks_bypass():
    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(
            lambda request: pytest.fail("late-installed guard must block queued raw create")
        ),
    )
    adapter._semaphore = asyncio.Semaphore(0)
    task = asyncio.create_task(
        adapter.private_post(
            "/v5/order/create",
            {"symbol": "BTCUSDT", "qty": "0.001", "orderLinkId": "queued-raw-bypass"},
        )
    )
    try:
        await asyncio.sleep(0)
        assert not task.done()
        adapter.set_order_guard(lambda order: None)
        adapter._semaphore.release()
        with pytest.raises(OrderNotSentError):
            await asyncio.wait_for(task, timeout=1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await adapter.close()


async def test_order_guard_does_not_block_verified_reads_or_order_cancellation():
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        return reply({"orderId": "fixture-cancel-id"})

    def guard(order):
        pytest.fail("reads/cancel must not invoke create-order admission guard")

    adapter = BybitDemoAdapter(credentials(), transport=httpx.MockTransport(handler))
    adapter.set_order_guard(guard)
    try:
        await adapter.private_get("/v5/account/info", {})
        await adapter.cancel_order("BTCUSDT", "fixture-cancel-id", "fixture-cancel-link")
        assert paths == ["/v5/account/info", "/v5/order/cancel"]
    finally:
        await adapter.close()


async def test_async_guard_cannot_silently_skip_validation_and_send_an_order():
    async def invalid_async_guard(order):
        raise RiskError("An asynchronous guard must never be accepted")

    adapter = BybitDemoAdapter(
        credentials(),
        transport=httpx.MockTransport(
            lambda request: pytest.fail("async guard cannot permit a request")
        ),
    )
    adapter.set_order_guard(invalid_async_guard)
    try:
        with pytest.raises(OrderNotSentError, match="sincrono"):
            await adapter.create_order(intent())
    finally:
        await adapter.close()
