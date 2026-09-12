import asyncio
from decimal import Decimal as D

import pytest
from gridbot.credentials import MemoryCredentialsStore
from gridbot.exchange import create_adapter
from gridbot.models import Credentials, Environment, StrategyConfig
from gridbot.runtime import BotRuntime
from gridbot.websocket import WebSocketManager
from mock_bybit import LoopbackTransport
from websockets.asyncio.client import connect


async def wait_for(predicate, timeout=4):
    end = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("Timed out waiting for condition")
        await asyncio.sleep(0.02)


def make_runtime(path, server, *, mainnet=False):
    credentials = MemoryCredentialsStore()
    credentials.save(
        Credentials(
            environment=Environment.DEMO,
            api_key=server.state.api_key,
            api_secret=server.state.api_secret,
        )
    )
    credentials.save(
        Credentials(
            environment=Environment.MAINNET,
            api_key=server.state.api_key,
            api_secret=server.state.api_secret,
        )
    )

    def adapter_factory(creds, **kwargs):
        return create_adapter(creds, transport=LoopbackTransport(server), **kwargs)

    def websocket_factory(adapter, symbol, on_event, on_status):
        def connector(url, **kwargs):
            path = "/v5/private" if "private" in url else "/v5/public/linear"
            kwargs["proxy"] = None
            kwargs.pop("ssl", None)  # Explicit test-only WSS-to-WS loopback redirect.
            return connect(server.ws_url + path, **kwargs)

        return WebSocketManager(
            adapter,
            symbol,
            on_event,
            on_status,
            connector=connector,
            heartbeat_interval=0.4,
            pong_timeout=0.5,
            reconnect_delay=0.1,
        )

    return BotRuntime(path, credentials, adapter_factory, websocket_factory, mainnet)


@pytest.mark.asyncio
async def test_actual_grid_pair_tp_pause_restart(local_bybit_server, tmp_path):
    server = local_bybit_server
    runtime = make_runtime(tmp_path, server)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.private_connected and runtime.public_connected)
        assert runtime.status == "READY"
        await runtime.configure(StrategyConfig(levels=2, debounce_ms=100))
        await runtime.start()
        await wait_for(lambda: len(server.state.orders) >= 4)
        assert runtime.status == "RUNNING", runtime.error
        assert len([o for o in server.state.orders.values() if not o["reduceOnly"]]) == 2
        assert {p["positionIdx"] for p in server.state.positions() if D(p["size"]) > 0} == {1, 2}
        await server.state.advance_market(D("67400"))
        await wait_for(lambda: len(server.state.orders) >= 8)
        assert runtime.status == "RUNNING", runtime.error
        assert len(await runtime.store.executions()) == 4
        state = await runtime.state()
        assert state["portfolio"]["fees"] is not None
        assert len(state["grid"]) == 4
        await runtime.pause()
        assert runtime.status == "PAUSED"
        created = len(server.state.orders)
        path = runtime.store.path
        await runtime.shutdown()
        runtime = make_runtime(tmp_path, server)
        await runtime.initialize()
        assert runtime.status == "DISCONNECTED"
        assert runtime.store.path == path
        assert len(await runtime.store.lots()) == 4
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.private_connected and runtime.public_connected)
        assert runtime.status == "READY"
        assert len(server.state.orders) == created
        await runtime.start()
        await asyncio.sleep(0.2)
        assert len(server.state.orders) == created
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_disconnect_pauses_and_never_resumes_entries(local_bybit_server, tmp_path):
    server = local_bybit_server
    runtime = make_runtime(tmp_path, server)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.private_connected and runtime.public_connected)
        await runtime.start()
        await wait_for(lambda: len(server.state.orders) >= 4)
        before = len(server.state.orders)
        await server.state.disconnect_private()
        await wait_for(lambda: runtime.status == "DEGRADED")
        await wait_for(lambda: runtime.private_connected)
        await server.state.advance_market(D("69000"))
        await asyncio.sleep(0.2)
        assert len(server.state.orders) == before
        assert runtime.status != "RUNNING"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_dedicated_account_external_position_blocks(local_bybit_server, tmp_path):
    server = local_bybit_server
    server.state.position_book[1] = {"qty": D(".01"), "average": D("67000")}
    runtime = make_runtime(tmp_path, server)
    await runtime.initialize()
    try:
        from gridbot.errors import RiskError

        with pytest.raises(RiskError):
            await runtime.connect(Environment.DEMO)
        assert runtime.status == "DEGRADED"
        assert len(server.state.orders) == 0
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_mainnet_default_gated_no_mutations(local_bybit_server, tmp_path):
    runtime = make_runtime(tmp_path, local_bybit_server)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.MAINNET)
        await wait_for(lambda: runtime.private_connected and runtime.public_connected)
        from gridbot.errors import RiskError

        with pytest.raises(RiskError):
            await runtime.start("AVVIA LIVE", True)
        assert len(local_bybit_server.state.orders) == 0
        assert runtime.store.path.parent.name == "LIVE"
    finally:
        await runtime.shutdown()
