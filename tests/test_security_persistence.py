from decimal import Decimal as D

import pytest
from gridbot.errors import DatabaseError
from gridbot.models import Environment, OrderIntent, Side, StrategyConfig
from gridbot.persistence import Store
from sqlalchemy import text
from test_runtime import make_runtime, wait_for


@pytest.mark.asyncio
async def test_secret_not_written_to_database_audit_configuration(local_bybit_server, tmp_path):
    server = local_bybit_server
    runtime = make_runtime(tmp_path, server)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        await runtime.configure(StrategyConfig(initial_pair=False))
        exported = (
            str(await runtime.state())
            + str(await runtime.store.records("configuration"))
            + str(await runtime.store.records("strategy_events"))
        )
        assert server.state.api_key not in exported
        assert server.state.api_secret not in exported
        for path in tmp_path.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                assert server.state.api_key.encode() not in data
                assert server.state.api_secret.encode() not in data
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_real_database_table_failure_pauses_before_exchange_create(
    local_bybit_server, tmp_path
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    await runtime.initialize()
    try:
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        await runtime.configure(StrategyConfig(initial_pair=False, levels=2))
        await runtime.start()
        async with runtime.store.engine.begin() as connection:
            await connection.execute(text("DROP TABLE orders"))
        await local_bybit_server.state.advance_market(D("67400"))
        await wait_for(lambda: runtime.status == "DEGRADED")
        assert runtime.reconciled is False
        assert len(local_bybit_server.state.orders) == 0
        assert "Errore" in runtime.error or "database" in runtime.error
    finally:
        # shutdown still must stop transports and engine after unrecoverable DB loss.
        try:
            await runtime.shutdown()
        except Exception:
            assert runtime.shutting_down
            assert runtime.status != "RUNNING"


@pytest.mark.asyncio
async def test_overclose_rolls_back_execution_order_lot_transaction(tmp_path):
    store = Store(tmp_path / "transaction.sqlite")
    await store.initialize()
    try:
        entry = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="entry",
            side=Side.SHORT,
            qty=D(4),
        )
        close = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="bad-close",
            side=Side.SHORT,
            qty=D(5),
            reduce_only=True,
            parent_link_id="entry",
            purpose="CLOSE",
        )
        await store.claim_intent(entry)
        await store.apply_execution(
            {
                "execId": "open",
                "orderId": "e",
                "orderLinkId": "entry",
                "side": "Sell",
                "execQty": "4",
                "execPrice": "100",
                "execFee": ".1",
                "execTime": "1800000000000",
            }
        )
        await store.claim_intent(close)
        with pytest.raises(DatabaseError):
            await store.apply_execution(
                {
                    "execId": "bad",
                    "orderId": "c",
                    "orderLinkId": "bad-close",
                    "side": "Buy",
                    "execQty": "5",
                    "execPrice": "90",
                    "execFee": ".1",
                    "execTime": "1800000000001",
                }
            )
        assert (await store.get_order("bad-close"))["executed_qty"] == "0"
        assert (await store.lots())[0]["qty"] == "4"
        assert len(await store.executions()) == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_duplicate_execution_contradiction_is_not_silently_accepted(tmp_path):
    store = Store(tmp_path / "exec.sqlite")
    await store.initialize()
    try:
        await store.claim_intent(
            OrderIntent(
                environment=Environment.DEMO,
                symbol="BTCUSDT",
                order_link_id="entry",
                side=Side.LONG,
                qty=D(2),
            )
        )
        payload = {
            "execId": "immutable",
            "orderId": "e",
            "orderLinkId": "entry",
            "side": "Buy",
            "execQty": "1",
            "execPrice": "100",
            "execFee": ".1",
            "execTime": "1800000000000",
        }
        assert await store.apply_execution(payload)
        assert not await store.apply_execution(payload)
        with pytest.raises(DatabaseError):
            await store.apply_execution({**payload, "execPrice": "101"})
        assert (await store.lots())[0]["entry"] == "100"
        assert len(await store.executions()) == 1
    finally:
        await store.close()
