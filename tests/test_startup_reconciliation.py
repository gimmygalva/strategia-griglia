"""Automatic saved-account restoration against the explicit Local Simulator."""

from decimal import Decimal

import pytest
from gridbot.credentials import MemoryCredentialsStore
from gridbot.errors import NetworkError, RiskError
from gridbot.models import Environment, StrategyConfig
from test_runtime import make_runtime, wait_for


class PersistentFixtureCredentials(MemoryCredentialsStore):
    """Test-only persistent interface; actual Mac Keychain has separate native QA."""

    @property
    def persistent(self):
        return True


def preserve_fixture_credentials(runtime):
    saved = PersistentFixtureCredentials()
    for environment in Environment:
        saved.save(runtime.credentials_store.load(environment))
    runtime.credentials_store = saved
    return saved


@pytest.mark.asyncio
async def test_saved_account_restores_actual_lots_and_orders_without_start(
    local_bybit_server, tmp_path
):
    server = local_bybit_server
    runtime = make_runtime(tmp_path, server)
    saved = preserve_fixture_credentials(runtime)
    await runtime.initialize()
    assert runtime.status == "DISCONNECTED"  # First run requires explicit verification.
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        await runtime.configure(StrategyConfig(levels=2))
        await runtime.start()
        await wait_for(lambda: len(server.state.orders) == 4)
        expected_lots = await runtime.store.lots()
        expected_session = runtime.session_id
        await runtime.shutdown()
        before = len(server.state.orders)
        runtime = make_runtime(tmp_path, server)
        runtime.credentials_store = saved
        await runtime.initialize()
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        assert runtime.status == "READY"
        assert runtime.reconciled
        assert runtime.session_id == expected_session
        assert await runtime.store.lots() == expected_lots
        assert all(Decimal(lot["qty"]) > 0 for lot in expected_lots)
        assert {position["positionIdx"] for position in runtime.exchange_positions} == {1, 2}
        assert len(server.state.orders) == before
        await server.state.advance_market(Decimal("69000"))
        assert runtime.status != "RUNNING"
        assert len(server.state.orders) == before
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_saved_mainnet_restoration_is_read_only_and_still_gated(local_bybit_server, tmp_path):
    runtime = make_runtime(tmp_path, local_bybit_server)
    saved = preserve_fixture_credentials(runtime)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.MAINNET)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        await runtime.shutdown()
        runtime = make_runtime(tmp_path, local_bybit_server)
        runtime.credentials_store = saved
        await runtime.initialize()
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        assert runtime.environment is Environment.MAINNET
        assert runtime.status == "READY"
        assert runtime.mainnet_allowed is False
        assert runtime.live_confirmed is False
        with pytest.raises(RiskError):
            await runtime.start("AVVIA LIVE", True)
        assert not local_bybit_server.state.orders
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_saved_account_network_failure_opens_paused_with_visible_error(
    local_bybit_server, tmp_path
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    saved = preserve_fixture_credentials(runtime)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await runtime.shutdown()
        runtime = make_runtime(tmp_path, local_bybit_server)
        runtime.credentials_store = saved

        def unavailable(credentials, **options):
            raise NetworkError("Local Simulator connection unavailable")

        runtime.adapter_factory = unavailable
        await runtime.initialize()
        assert runtime.status == "DEGRADED"
        assert runtime.connected is False
        assert runtime.reconciled is False
        assert runtime.live_confirmed is False
        assert runtime.error == "Local Simulator connection unavailable"
        assert not local_bybit_server.state.orders
        assert await runtime.store.records("errors")
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_saved_account_timeout_cancels_request_and_keeps_local_app_usable(
    local_bybit_server, tmp_path, monkeypatch
):
    import asyncio

    import gridbot.connection as account_connection

    runtime = make_runtime(tmp_path, local_bybit_server)
    saved = preserve_fixture_credentials(runtime)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await runtime.shutdown()
        runtime = make_runtime(tmp_path, local_bybit_server)
        runtime.credentials_store = saved
        original_factory = runtime.adapter_factory
        cancelled = asyncio.Event()

        async def blocked_instrument(symbol):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        def delayed(credentials, **options):
            adapter = original_factory(credentials, **options)
            adapter.instrument = blocked_instrument
            return adapter

        runtime.adapter_factory = delayed
        monkeypatch.setattr(account_connection, "STARTUP_ACCOUNT_TIMEOUT_SECONDS", 0.05)
        await runtime.initialize()
        assert cancelled.is_set()
        assert runtime.adapter is None
        assert runtime.status == "DEGRADED"
        assert runtime.connected is False
        assert runtime.reconciled is False
        assert "scaduta" in runtime.error
        assert not local_bybit_server.state.orders
        assert await runtime.store.records("errors")
    finally:
        await runtime.shutdown()
