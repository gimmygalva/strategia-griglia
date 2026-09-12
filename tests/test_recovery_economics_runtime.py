"""Funding-aware recovery exits verified against actual local HTTP/WS fills.

The assertions use exchange execution cash flows rather than production pricing
helpers. This fixture is exclusively a Local Simulator, never Bybit Demo Trading.
"""

from decimal import Decimal as D

import pytest
from gridbot.models import Side
from gridbot.orders import TERMINAL
from test_recovery_runtime_math import eventually_async, prepare_losing_lot
from test_runtime import make_runtime


async def activate_recovery(runtime, server, side):
    await prepare_losing_lot(runtime, server, side)
    await runtime.inject(side, True)

    async def injection_confirmed():
        return len(await runtime.store.executions()) == 2

    await eventually_async(injection_confirmed)
    async with runtime.lock:
        await runtime._recovery_protection()
    active = await active_block_tps(runtime, side)
    assert len(active) == 1
    return active[0]


async def active_block_tps(runtime, side):
    return [
        row
        for row in await runtime.store.orders()
        if row["purpose"] == "RECOVERY_TP"
        and row["side"] == side.value
        and row["state"] not in TERMINAL
    ]


def adverse_exit_net(server, runtime, side, quote):
    """Independently settle the remaining position at a modeled adverse exit."""
    entries = server.state.executions
    assert len(entries) == 2
    assert all(D(execution["closedSize"]) == 0 for execution in entries)
    expected_side = "Buy" if side == Side.LONG else "Sell"
    assert all(execution["side"] == expected_side for execution in entries)
    qty = sum((D(execution["execQty"]) for execution in entries), D(0))
    cost = sum((D(execution["execQty"]) * D(execution["execPrice"]) for execution in entries), D(0))
    fees_paid = sum((D(execution["execFee"]) for execution in entries), D(0))
    funding = sum((D(transaction["funding"]) for transaction in server.state.transactions), D(0))
    slip = runtime.config.slippage_pct / 100
    effective_exit = D(quote) * (1 - slip if side == Side.LONG else 1 + slip)
    gross = (qty * effective_exit - cost) * (1 if side == Side.LONG else -1)
    estimated_exit_fee = qty * effective_exit * server.state.fee_rate
    return gross - fees_paid - estimated_exit_fee + funding


async def finish_and_assert_actual_cash_flow(runtime, server, side, tp):
    await runtime.pause()
    await server.state.fill(tp["order_id"], price=D(tp["price"]))

    async def flat_position():
        return not await runtime.store.lots()

    await eventually_async(flat_position)
    async with runtime.lock:
        await runtime._reconcile()
        await runtime._recovery_protection()
    assert side.value not in runtime.active_recovery
    assert server.state.position_book[side.position_idx]["qty"] == 0
    # A fully closed linear position's signed entry/exit notionals give exact
    # gross cash-flow PnL. Subtract every real fee and add signed settlement.
    cash_flow = sum(
        (
            D(execution["execQty"])
            * D(execution["execPrice"])
            * (-1 if execution["side"] == "Buy" else 1)
            - D(execution["execFee"])
            for execution in server.state.executions
        ),
        D(0),
    ) + sum((D(transaction["funding"]) for transaction in server.state.transactions), D(0))
    assert cash_flow >= runtime.config.recovery_profit_target_usdt
    values = await runtime.portfolio()
    assert abs(D(values["net"]) - cash_flow) < D("1e-20")
    assert abs(D(values["grid"])) < D("1e-20")
    assert abs(D(values["recovery"]) + D(values["funding"]) - cash_flow) < D("1e-20")


@pytest.mark.asyncio
@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
async def test_settled_funding_debit_reprices_recovery_tp_without_new_injection(
    local_bybit_server, tmp_path, side
):
    server = local_bybit_server
    runtime = make_runtime(tmp_path, server)
    try:
        old_tp = await activate_recovery(runtime, server, side)
        old_generation = runtime.recovery_info[side.value].get("tp_generation", 0)
        original_qty = D(old_tp["qty"])
        created_before = len(server.state.orders)
        calls_before = len(server.state.calls)
        funding = await server.state.settle_funding(
            "Buy" if side == Side.LONG else "Sell", D("-.5")
        )
        async with runtime.lock:
            await runtime._reconcile()
            await runtime._recovery_protection()
        settlements = await runtime.store.funding_events()
        assert len(settlements) == 1 and settlements[0]["id"] == funding["id"]
        assert D(settlements[0]["amount"]) == D("-.5")
        active = await active_block_tps(runtime, side)
        assert len(active) == 1
        corrected = active[0]
        assert corrected["order_link_id"] != old_tp["order_link_id"]
        assert corrected["order_id"] != old_tp["order_id"]
        assert D(corrected["qty"]) == original_qty
        assert corrected["pair_id"] == old_tp["pair_id"]
        if side == Side.LONG:
            assert D(corrected["price"]) > D(old_tp["price"])
        else:
            assert D(corrected["price"]) < D(old_tp["price"])
        assert adverse_exit_net(server, runtime, side, old_tp["price"]) < (
            runtime.config.recovery_profit_target_usdt
        )
        assert adverse_exit_net(server, runtime, side, corrected["price"]) >= (
            runtime.config.recovery_profit_target_usdt - D("1e-20")
        )
        canceled = await runtime.store.get_order(old_tp["order_link_id"])
        assert canceled["state"] == "CANCELED"
        assert server.state.orders[old_tp["order_id"]]["orderStatus"] == "Cancelled"
        assert len(server.state.orders) == created_before + 1
        orders = await runtime.store.orders()
        assert len([row for row in orders if row["purpose"] == "RECOVERY"]) == 1
        assert runtime.recovery_info[side.value]["tp_generation"] == old_generation + 1
        persisted = await runtime.store.get("recovery_blocks", "active")
        assert persisted["info"][side.value]["tp_generation"] == old_generation + 1
        calls = server.state.calls[calls_before:]
        cancel_index = next(
            index
            for index, call in enumerate(calls)
            if call["path"] == "/v5/order/cancel"
            and call["body"]["orderLinkId"] == old_tp["order_link_id"]
        )
        create_index = next(
            index
            for index, call in enumerate(calls)
            if call["path"] == "/v5/order/create"
            and call["body"]["orderLinkId"] == corrected["order_link_id"]
        )
        assert cancel_index < create_index
        assert any(
            call["path"] in {"/v5/order/realtime", "/v5/order/history"}
            for call in calls[cancel_index + 1 : create_index]
        )
        async with runtime.lock:
            for _ in range(2):
                await runtime._reconcile()
                await runtime._recovery_protection()
        assert len(server.state.orders) == created_before + 1
        assert len(await runtime.store.funding_events()) == 1
        assert (await active_block_tps(runtime, side))[0]["order_id"] == corrected["order_id"]
        assert runtime.recovery_info[side.value]["tp_generation"] == old_generation + 1
        await finish_and_assert_actual_cash_flow(runtime, server, side, corrected)
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
async def test_positive_settled_funding_retains_better_existing_recovery_tp(
    local_bybit_server, tmp_path, side
):
    server = local_bybit_server
    runtime = make_runtime(tmp_path, server)
    try:
        original = await activate_recovery(runtime, server, side)
        old_generation = runtime.recovery_info[side.value].get("tp_generation", 0)
        created = len(server.state.orders)
        calls_before = len(server.state.calls)
        await server.state.settle_funding("Buy" if side == Side.LONG else "Sell", D(".5"))
        async with runtime.lock:
            for _ in range(2):
                await runtime._reconcile()
                await runtime._recovery_protection()
        active = await active_block_tps(runtime, side)
        assert len(active) == 1
        retained = active[0]
        assert retained["order_id"] == original["order_id"]
        assert retained["order_link_id"] == original["order_link_id"]
        assert retained["price"] == original["price"]
        assert D(retained["qty"]) == D(original["qty"])
        assert runtime.recovery_info[side.value].get("tp_generation", 0) == old_generation
        assert len(server.state.orders) == created
        assert not any(
            call["path"] in {"/v5/order/create", "/v5/order/cancel"}
            for call in server.state.calls[calls_before:]
        )
        assert len(await runtime.store.funding_events()) == 1
        assert adverse_exit_net(server, runtime, side, retained["price"]) >= (
            runtime.config.recovery_profit_target_usdt + D(".5") - D("1e-20")
        )
        await finish_and_assert_actual_cash_flow(runtime, server, side, retained)
    finally:
        await runtime.shutdown()
