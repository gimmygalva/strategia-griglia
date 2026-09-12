"""Release-audit regressions for coherent snapshots, clocks and stale valuation."""

import asyncio
import json
import logging
import time
from decimal import Decimal as D
from unittest.mock import patch

import httpx
import pytest
from gridbot.__main__ import AuditFormatter
from gridbot.api import create_app
from gridbot.credentials import MemoryCredentialsStore
from gridbot.errors import OrderNotSentError, RiskError
from gridbot.grid import GridEngine
from gridbot.models import Environment, OrderIntent, Side, StrategyConfig
from gridbot.runtime import BotRuntime
from test_recovery_economics_runtime import activate_recovery
from test_runtime import make_runtime, wait_for


@pytest.mark.asyncio
async def test_ui_snapshot_waits_for_actor_transaction(tmp_path):
    runtime = BotRuntime(tmp_path, credentials_store=MemoryCredentialsStore())
    await runtime.initialize()
    try:
        async with runtime.lock:
            snapshot = asyncio.create_task(runtime.state())
            await asyncio.sleep(0.03)
            assert not snapshot.done(), "UI read bypassed the strategy transaction"
        state = await asyncio.wait_for(snapshot, 2)
        assert state["status"] == "DISCONNECTED"
        assert state["portfolio"]["net"] is None
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_wizard_cannot_overwrite_session_metadata_while_start_commits(tmp_path):
    runtime = BotRuntime(tmp_path, credentials_store=MemoryCredentialsStore())
    await runtime.initialize()
    token = "local-actor-test-token"
    app = create_app(runtime, token, 1234, None)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:1234"
        ) as client:
            async with runtime.lock:
                completion = asyncio.create_task(
                    client.post(
                        "/api/wizard",
                        json={"completed": True},
                        headers={"Authorization": "Bearer " + token},
                    )
                )
                await asyncio.sleep(0.03)
                assert not completion.done(), "Wizard bypassed Start's metadata transaction"
                runtime.session_id = "new-committed-grid-session"
                await runtime.store.put(
                    "configuration",
                    "app",
                    {"wizard_completed": False, "session_id": runtime.session_id},
                )
            assert (await asyncio.wait_for(completion, 2)).status_code == 200
        metadata = await runtime.store.get("configuration", "app")
        assert metadata == {"wizard_completed": True, "session_id": "new-committed-grid-session"}
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_fresh_last_price_cannot_authorize_order_with_stale_mark(
    local_bybit_server, tmp_path
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        await runtime.configure(StrategyConfig(initial_pair=False, levels=2))
        await runtime.start()
        intent = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="audit-stale-mark",
            side=Side.LONG,
            qty="0.001",
        )
        async with runtime.lock:
            runtime.last_public = time.monotonic()
            runtime.last_mark = time.monotonic() - 16
            with pytest.raises(RiskError):
                await runtime.manager.submit(intent)
            assert len(local_bybit_server.state.orders) == 0
            assert await runtime.store.get_order(intent.order_link_id) is None
            await runtime._fetch_prices()
            assert (await runtime.risk_context(intent)).connected is True
    finally:
        await runtime.shutdown()


def test_exchange_clock_offset_is_used_for_business_timestamps(tmp_path):
    runtime = BotRuntime(tmp_path)
    runtime.adapter = type("ClockAdapter", (), {"clock_offset_ms": -2500})()
    with patch("gridbot.runtime.time.time", return_value=1000):
        assert runtime.exchange_time_ms() == 997500


@pytest.mark.asyncio
async def test_running_api_config_changes_only_auto_recovery(local_bybit_server, tmp_path):
    runtime = make_runtime(tmp_path, local_bybit_server)
    await runtime.initialize()
    token = "local-config-test-token"
    app = create_app(runtime, token, 1234, None)
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        await runtime.configure(StrategyConfig(initial_pair=False, levels=2))
        await runtime.start()
        grid = runtime.grid.snapshot()
        session_id = runtime.session_id
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:1234"
        ) as client:
            for enabled in [True, False]:
                config = runtime.config.model_dump(mode="json") | {"auto_recovery": enabled}
                response = await client.post(
                    "/api/config", json=config, headers={"Authorization": "Bearer " + token}
                )
                assert response.status_code == 200
                assert runtime.config.auto_recovery is enabled
                assert runtime.manager.config.auto_recovery is enabled
                assert (await runtime.store.get("configuration", "strategy"))[
                    "auto_recovery"
                ] is enabled
                assert runtime.grid.snapshot() == grid and runtime.session_id == session_id
                assert runtime.status == "RUNNING"
                audit = (
                    await client.get("/api/events", headers={"Authorization": "Bearer " + token})
                ).json()
                changes = [
                    row["details"]["changes"] for row in audit if row["event"] == "settings_changed"
                ]
                assert {"auto_recovery": {"before": not enabled, "after": enabled}} in changes
            blocked = runtime.config.model_dump(mode="json") | {"levels": 5}
            response = await client.post(
                "/api/config", json=blocked, headers={"Authorization": "Bearer " + token}
            )
            assert response.status_code == 409 and response.json()["detail"]["code"] == "RISK_ERROR"
            assert runtime.config.levels == 2
            assert (await runtime.store.get("configuration", "strategy"))["levels"] == 2
            assert runtime.grid.snapshot() == grid and runtime.session_id == session_id
            assert len(local_bybit_server.state.orders) == 0
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_active_recovery_auto_switch_preserves_confirmed_tp(local_bybit_server, tmp_path):
    runtime = make_runtime(tmp_path, local_bybit_server)
    try:
        tp = await activate_recovery(runtime, local_bybit_server, Side.SHORT)
        orders = len(local_bybit_server.state.orders)
        info = dict(runtime.recovery_info["SHORT"])
        for enabled in [True, False]:
            config = StrategyConfig.model_validate(
                runtime.config.model_dump() | {"auto_recovery": enabled}
            )
            await runtime.configure(config)
            assert runtime.config.auto_recovery is enabled
            assert "SHORT" in runtime.active_recovery
            assert runtime.recovery_info["SHORT"] == info
            assert (await runtime.store.get_order(tp["order_link_id"]))["order_id"] == tp[
                "order_id"
            ]
            assert len(local_bybit_server.state.orders) == orders
        changed = StrategyConfig.model_validate(
            runtime.config.model_dump() | {"max_injection_usdt": "2000"}
        )
        with pytest.raises(RiskError):
            await runtime.configure(changed)
        assert len(local_bybit_server.state.orders) == orders
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_disconnect_during_intent_commit_vetoes_send(local_bybit_server, tmp_path):
    runtime = make_runtime(tmp_path, local_bybit_server)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        await runtime.configure(StrategyConfig(initial_pair=False, levels=2))
        await runtime.start()
        claim = runtime.store.claim_intent

        async def commit_then_disconnect(intent):
            result = await claim(intent)
            await runtime.on_status("private", False)
            return result

        runtime.store.claim_intent = commit_then_disconnect
        intent = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="audit-disconnect-after-commit",
            side=Side.LONG,
            qty="0.001",
        )
        async with runtime.lock:
            with pytest.raises(OrderNotSentError):
                await runtime.manager.submit(intent)
        row = await runtime.store.get_order(intent.order_link_id)
        assert row["state"] == "REJECTED" and row["error"] == "ORDER_NOT_SENT"
        assert row["order_id"] is None
        assert len(local_bybit_server.state.orders) == 0
        assert runtime.manager.uncertain is False
        assert runtime.status == "DEGRADED"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("during_commit", [False, True])
async def test_received_funding_vetoes_send_while_actor_is_busy(
    local_bybit_server, tmp_path, during_commit
):
    server = local_bybit_server
    runtime = make_runtime(tmp_path, server)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        await runtime.start()
        await wait_for(lambda: len(server.state.orders) == 4)
        created = len(server.state.orders)

        async def receive_settlement():
            await server.state.settle_funding("Buy", D("-.5"))
            await server.state.broadcast("execution", [{"execType": "Funding"}])
            await wait_for(lambda: runtime.ws.pending_funding > 0)

        claim = runtime.store.claim_intent
        if during_commit:

            async def commit_then_receive_funding(intent):
                result = await claim(intent)
                await receive_settlement()
                return result

            runtime.store.claim_intent = commit_then_receive_funding

        intent = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="audit-funding-during-commit"
            if during_commit
            else "audit-funding-backlog",
            side=Side.LONG,
            qty="0.001",
        )
        async with runtime.lock:
            if not during_commit:
                await receive_settlement()
            error = OrderNotSentError if during_commit else RiskError
            with pytest.raises(error):
                await runtime.manager.submit(intent)
            assert len(server.state.orders) == created
            row = await runtime.store.get_order(intent.order_link_id)
            if during_commit:
                assert row["state"] == "REJECTED" and row["error"] == "ORDER_NOT_SENT"
                assert row["order_id"] is None
            else:
                assert row is None
        await wait_for(lambda: runtime.status == "DEGRADED" and runtime.ws.pending_funding == 0)
        assert runtime.manager.uncertain is False
        async with runtime.lock:
            await runtime._reconcile()
        funding = await runtime.store.funding_events()
        assert len(funding) == 1 and D(funding[0]["amount"]) == D("-.5")
        assert len(server.state.orders) == created
        assert runtime.status != "RUNNING"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_confirmed_close_all_reduces_both_sides_without_reopening(
    local_bybit_server, tmp_path
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        await runtime.start()
        await wait_for(lambda: len(local_bybit_server.state.orders) == 4)
        assert len(await runtime.store.lots()) == 2
        await runtime.close_all("CHIUDI TUTTO", True)

        async def closed():
            for _ in range(100):
                if not await runtime.store.lots():
                    return
                await asyncio.sleep(0.03)
            raise AssertionError("Confirmed hedge reductions did not reach the execution ledger")

        await closed()
        orders = await runtime.store.orders()
        reductions = [row for row in orders if row["purpose"] == "CLOSE"]
        assert len(reductions) == 2
        assert {row["side"] for row in reductions} == {"LONG", "SHORT"}
        assert all(row["reduce_only"] for row in reductions)
        assert all(D(row["size"]) == 0 for row in local_bybit_server.state.positions())
        assert all(row["state"] == "CANCELED" for row in orders if row["purpose"] == "TP")
        # Queued older position reports can conservatively pause after REST closes.
        # The real monitor must reconcile them, without a test-side state reset.
        await wait_for(lambda: runtime.status == "PAUSED" and runtime.reconciled, timeout=12)
        assert runtime.status == "PAUSED"
        count = len(local_bybit_server.state.orders)
        await local_bybit_server.state.advance_market(D(68000))
        await asyncio.sleep(0.1)
        assert len(local_bybit_server.state.orders) == count
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_grid_configuration_reset_survives_restart_before_next_start(tmp_path):
    runtime = BotRuntime(tmp_path, credentials_store=MemoryCredentialsStore())
    await runtime.initialize()
    runtime.session_id = "old-grid-session"
    runtime.grid = GridEngine(D(67000), D(".005"), 20, D(".1"), D(".5"), 3000)
    await runtime.store.save_grid(runtime.grid.snapshot(), runtime.session_id)
    await runtime.store.put(
        "configuration", "app", {"wizard_completed": True, "session_id": runtime.session_id}
    )
    runtime.wizard_completed = True
    await runtime.configure(StrategyConfig(spacing_pct="1", levels=5))
    await runtime.shutdown()
    restarted = BotRuntime(tmp_path, credentials_store=MemoryCredentialsStore())
    await restarted.initialize()
    try:
        assert restarted.config.spacing_pct == D(1)
        assert restarted.config.levels == 5
        assert restarted.grid is None and restarted.session_id is None
        assert restarted.wizard_completed is True
        assert restarted.status == "DISCONNECTED"
    finally:
        await restarted.shutdown()


def test_structured_log_has_identifiers_and_drops_message_and_exception():
    secret = "local-security-fixture-do-not-log"
    record = logging.LogRecord("gridbot", logging.ERROR, __file__, 1, secret, (), None)
    record.exc_text = secret
    record.event = "order_rejected"
    record.environment = "DEMO"
    record.correlation_id = "session-1"
    record.order_id = "exchange-1"
    record.pair_id = "pair-1"
    record.level_id = "level-1"
    record.symbol = "BTCUSDT"
    rendered = AuditFormatter().format(record)
    assert secret not in rendered
    values = json.loads(rendered)
    assert values["order_id"] == "exchange-1"
    assert values["correlation_id"] == "session-1"
    assert values["environment"] == "DEMO"
    assert values["timestamp"].endswith("+00:00")
