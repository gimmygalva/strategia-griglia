"""Independent cash-flow assertions and production-runtime local-server recovery tests."""

import asyncio
import time
from decimal import Decimal as D

import pytest
from gridbot.errors import RecoveryError, RiskError, ValidationError
from gridbot.models import Environment, OrderIntent, Side, StrategyConfig
from gridbot.pnl import calculate_portfolio, midnight_unrealized, recovery_exit_budget
from gridbot.recovery import break_even
from test_runtime import make_runtime, wait_for


def execution(link, side, qty, price, fee, pnl, timestamp, purpose="GRID", allocations=None):
    return {
        "exec_id": f"{link}-{timestamp}",
        "link_id": link,
        "side": str(side),
        "qty": str(qty),
        "price": str(price),
        "fee": str(fee),
        "realized_pnl": str(pnl),
        "time_ms": str(timestamp),
        "purpose": purpose,
        "payload": {"_allocations": allocations} if allocations is not None else {},
    }


def order(link, side="LONG", purpose="GRID", reduce_only=False, parent=None):
    return {
        "order_link_id": link,
        "side": side,
        "purpose": purpose,
        "reduce_only": reduce_only,
        "parent_link_id": parent,
    }


def membership(side, links, fee, timestamp=400):
    return {
        "activation_time_ms": timestamp,
        "side": side,
        "member_links": links,
        "entry_fees_reclassified": str(fee),
    }


def active_cash_flow():
    executions = [
        execution("old", "LONG", "2", "100", ".2", "0", 100),
        execution("early-tp", "LONG", "1", "110", ".11", "10", 200, "TP"),
        execution("new", "LONG", "1", "120", ".12", "0", 300),
        execution("injection", "LONG", "2", "90", ".18", "0", 500, "RECOVERY"),
    ]
    lots = [
        {"order_link_id": "old", "side": "LONG", "qty": "1", "entry": "100", "purpose": "GRID"},
        {"order_link_id": "new", "side": "LONG", "qty": "1", "entry": "120", "purpose": "GRID"},
        {
            "order_link_id": "injection",
            "side": "LONG",
            "qty": "2",
            "entry": "90",
            "purpose": "RECOVERY",
        },
    ]
    orders = [
        order("old"),
        order("new"),
        order("injection", purpose="RECOVERY"),
        order("early-tp", purpose="TP", reduce_only=True, parent="old"),
    ]
    records = [membership("LONG", ["old", "new"], ".22")]
    funding = [{"amount": "-.07", "side": "LONG"}]
    return executions, lots, funding, orders, records


def test_actual_active_recovery_bucket_contains_losses_and_original_entry_fees():
    values = calculate_portfolio(*active_cash_flow(), D(100))
    assert values["realized"] == 10
    assert values["unrealized"] == 0
    assert values["fees"] == D(".61")
    assert values["funding"] == D("-.07")
    assert values["recovery"] == D("-.4")
    assert values["grid"] == D("9.79")
    assert values["net"] == D("9.32")
    assert values["long"] == values["net"] and values["short"] == 0
    assert values["grid"] + values["recovery"] + values["funding"] == values["net"]


def test_standard_tp_after_membership_belongs_to_recovery_without_reclassifying_earlier_grid_profit():
    executions, lots, funding, orders, records = active_cash_flow()
    executions.append(execution("late-tp", "LONG", 1, 101, ".101", -19, 600, "TP"))
    orders.append(order("late-tp", purpose="TP", reduce_only=True, parent="new"))
    lots = [lot for lot in lots if lot["order_link_id"] != "new"]
    values = calculate_portfolio(executions, lots, funding, orders, records, D(100))
    assert values["grid"] == D("9.79")
    assert values["recovery"] == D(".499")
    assert values["net"] == D("10.219")


def test_mixed_close_all_uses_actual_allocations_for_grid_recovery_and_fee_split():
    executions = [
        execution("grid", "LONG", 1, 100, ".1", 0, 100),
        execution("member", "LONG", 1, 120, ".12", 0, 200),
        execution("injection", "LONG", 1, 90, ".09", 0, 500, "RECOVERY"),
        execution(
            "close",
            "LONG",
            3,
            110,
            ".33",
            20,
            600,
            "CLOSE",
            [
                {"link_id": "grid", "qty": "1", "realized_pnl": "10", "entry_fee_allocated": ".1"},
                {
                    "link_id": "member",
                    "qty": "1",
                    "realized_pnl": "-10",
                    "entry_fee_allocated": ".12",
                },
                {
                    "link_id": "injection",
                    "qty": "1",
                    "realized_pnl": "20",
                    "entry_fee_allocated": ".09",
                },
            ],
        ),
    ]
    orders = [
        order("grid"),
        order("member"),
        order("injection", purpose="RECOVERY"),
        order("close", purpose="CLOSE", reduce_only=True),
    ]
    values = calculate_portfolio(
        executions, [], [], orders, [membership("LONG", ["member"], ".12")], D(110)
    )
    assert values["grid"] == D("9.79")
    assert values["recovery"] == D("9.57")
    assert values["net"] == D("19.36")
    assert values["grid"] + values["recovery"] == values["net"]


def test_signed_reclassified_rebate_is_transferred_once_and_duplicate_record_is_idempotent():
    executions = [
        execution("old", "SHORT", 1, 100, "-.1", 0, 100),
        execution("recovery-tp", "SHORT", 1, 90, ".09", 10, 600, "RECOVERY_TP"),
    ]
    orders = [order("old", "SHORT"), order("recovery-tp", "SHORT", "RECOVERY_TP", True)]
    record = membership("SHORT", ["old"], "-.1")
    values = calculate_portfolio(executions, [], [], orders, [record, dict(record)], D(90))
    assert values["grid"] == 0
    assert values["recovery"] == D("10.01")
    assert values["fees"] == D("-.01")


def test_two_sides_and_signed_funding_match_cash_total_without_hiding_funding_in_grid():
    executions = [
        execution("long", "LONG", 1, 100, ".1", 0, 100),
        execution("short", "SHORT", 2, 120, ".24", 0, 100),
    ]
    lots = [
        {"order_link_id": "long", "side": "LONG", "qty": "1", "entry": "100", "purpose": "GRID"},
        {"order_link_id": "short", "side": "SHORT", "qty": "2", "entry": "120", "purpose": "GRID"},
    ]
    funding = [{"amount": "-.07", "side": "LONG"}, {"amount": ".11", "side": "SHORT"}]
    values = calculate_portfolio(
        executions, lots, funding, [order("long"), order("short", "SHORT")], [], D(110)
    )
    assert values["long"] == D("9.83")
    assert values["short"] == D("19.87")
    assert values["net"] == D("29.70")
    assert values["grid"] == D("29.66") and values["funding"] == D(".04")


def test_contradictory_close_allocations_fail_closed():
    executions = [
        execution(
            "close",
            "LONG",
            1,
            100,
            ".1",
            1,
            600,
            "CLOSE",
            [{"link_id": "member", "qty": "1", "realized_pnl": "2"}],
        )
    ]
    with pytest.raises(ValidationError, match="Allocazioni"):
        calculate_portfolio(
            executions, [], [], [order("close", purpose="CLOSE", reduce_only=True)], [], D(100)
        )


def historic_partial_close_ledger(allocations=True):
    close_allocation = (
        [{"link_id": "long", "qty": "3", "realized_pnl": "30"}] if allocations else None
    )
    ledger = [
        execution("long", "LONG", 4, 100, ".4", 0, 100),
        execution("partial-close", "LONG", 3, 110, ".33", 30, 200, "TP", close_allocation),
        execution("long", "LONG", 2, 120, ".24", 0, 300),
        execution("short", "SHORT", 2, 150, ".3", 0, 200),
    ]
    orders = [
        order("long"),
        order("partial-close", purpose="TP", reduce_only=True, parent="long"),
        order("short", "SHORT"),
    ]
    return ledger, orders


@pytest.mark.parametrize("allocations", [True, False])
def test_midnight_reconstructs_remaining_cost_after_partial_close_then_late_entry_fill(allocations):
    ledger, orders = historic_partial_close_ledger(allocations)
    assert midnight_unrealized(ledger, orders, D(110), 1000) == D(70)
    # A cumulative filled entry average would incorrectly use (400+240)/6.
    assert midnight_unrealized(ledger, orders, D(120), 1000) == D(80)


def test_daily_loss_uses_midnight_mark_including_carry_positions_and_today_cash_fees_funding():
    ledger, orders = historic_partial_close_ledger()
    baseline = midnight_unrealized(ledger, orders, D(110), 1000)
    entry = D(340) / 3
    profit = D(115) - entry
    ledger.append(
        execution(
            "today-close",
            "LONG",
            1,
            115,
            ".115",
            profit,
            1100,
            "TP",
            [{"link_id": "long", "qty": "1", "realized_pnl": str(profit)}],
        )
    )
    ledger.append(execution("short", "SHORT", 1, 130, ".13", 0, 1200))
    orders.append(order("today-close", purpose="TP", reduce_only=True, parent="long"))
    lots = [
        {
            "order_link_id": "long",
            "side": "LONG",
            "qty": "2",
            "entry": str(entry),
            "purpose": "GRID",
        },
        {
            "order_link_id": "short",
            "side": "SHORT",
            "qty": "3",
            "entry": str(D(430) / 3),
            "purpose": "GRID",
        },
    ]
    funding = [{"amount": "-.5", "side": "LONG", "time_ms": "1150"}]
    current = calculate_portfolio(ledger, lots, funding, orders, [], D(120))
    day_cash = sum(
        (D(row["realized_pnl"]) - D(row["fee"]) for row in ledger if int(row["time_ms"]) >= 1000),
        D(0),
    ) + D("-.5")
    day_pnl = day_cash + current["unrealized"] - baseline
    assert abs(day_pnl - D("14.255")) < D("1e-23")
    midnight_net = D(30) + D(70) - D("1.27")
    assert abs(current["net"] - midnight_net - day_pnl) < D("1e-23")


def test_midnight_exact_boundary_excludes_fills_at_or_after_day_start():
    ledger = [
        execution("long", "LONG", 1, 100, ".1", 0, 999),
        execution("short", "SHORT", 1, 120, ".12", 0, 1000),
    ]
    assert midnight_unrealized(ledger, [order("long"), order("short", "SHORT")], D(110), 1000) == 10


def test_midnight_incomplete_owned_ledger_blocks_instead_of_assuming_zero():
    ledger = [execution("close", "LONG", 1, 100, ".1", 1, 500, "CLOSE")]
    with pytest.raises(ValidationError):
        midnight_unrealized(
            ledger, [order("close", purpose="CLOSE", reduce_only=True)], D(100), 1000
        )


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_recovery_exit_budget_independent_full_block_cash_flow_after_partial_close(side):
    average, injection_price, prior_exit = (
        (D(100), D(90), D(105)) if side == Side.LONG else (D(120), D(130), D(115))
    )
    original_fee = 2 * average * D(".001")
    injection_fee = 3 * injection_price * D(".001")
    closing_fee = prior_exit * D(".001")
    realized = D(10)
    info = {
        **membership(side.value, ["member"], original_fee),
        "injection_id": "injection",
    }
    ledger = [
        # Original entry cost is taken only from the persisted remaining cost at
        # activation, rather than adding this historical full entry fee again.
        execution("member", side, 3, average, 3 * average * D(".001"), 0, 100),
        execution("early-tp", side, 1, average, average * D(".001"), 0, 200, "TP"),
        execution("injection", side, 3, injection_price, injection_fee, 0, 500, "RECOVERY"),
        execution(
            "partial",
            side,
            1,
            prior_exit,
            closing_fee,
            realized,
            600,
            "CLOSE",
            [
                {
                    "link_id": "member",
                    "qty": ".5",
                    "realized_pnl": "2.5",
                    "entry_fee_allocated": str(original_fee / 4),
                },
                {
                    "link_id": "injection",
                    "qty": ".5",
                    "realized_pnl": "7.5",
                    "entry_fee_allocated": str(injection_fee / 6),
                },
            ],
        ),
    ]
    orders = [
        order("member", side.value),
        order("early-tp", side.value, "TP", True, "member"),
        order("injection", side.value, "RECOVERY"),
        order("partial", side.value, "CLOSE", True),
    ]
    funding = [{"side": side.value, "amount": "-.03", "time_ms": "550"}]
    budget = recovery_exit_budget(info, ledger, orders, funding)
    assert budget == original_fee + injection_fee + closing_fee - realized + D(".03")
    remaining_qty = D(4)
    remaining_avg = (D("1.5") * average + D("2.5") * injection_price) / remaining_qty
    exit_fee, exit_slippage, profit_target = D(".0006"), D(".001"), D("1.2")
    quoted = break_even(
        side, remaining_qty, remaining_avg, budget, exit_fee, exit_slippage, profit_target
    )
    actual_exit = quoted * (1 - exit_slippage if side == Side.LONG else 1 + exit_slippage)
    sign = 1 if side == Side.LONG else -1
    full_net = (
        realized
        + sign * remaining_qty * (actual_exit - remaining_avg)
        - original_fee
        - injection_fee
        - closing_fee
        - remaining_qty * actual_exit * exit_fee
        - D(".03")
    )
    assert abs(full_net - profit_target) < D("1e-23")


def test_recovery_exit_budget_mixed_close_allocations_ignore_foreign_lots_and_old_blocks():
    info = {**membership("LONG", ["member"], ".2"), "injection_id": "injection"}
    allocations = [
        {"link_id": "member", "qty": "1", "realized_pnl": "-3", "entry_fee_allocated": ".1"},
        {"link_id": "injection", "qty": "2", "realized_pnl": "8", "entry_fee_allocated": ".2"},
        {"link_id": "foreign", "qty": "3", "realized_pnl": "20", "entry_fee_allocated": "9"},
    ]
    old_tp = order("old-tp", purpose="RECOVERY_TP", reduce_only=True)
    old_tp["pair_id"] = "old-injection"
    ledger = [
        execution("injection", "LONG", 2, 100, ".3", 0, 500, "RECOVERY"),
        execution("mixed", "LONG", 6, 100, ".6", 25, 600, "CLOSE", allocations),
        execution("old-tp", "LONG", 1, 100, ".1", 7, 650, "RECOVERY_TP"),
        execution("unrelated", "LONG", 1, 100, ".1", 3, 650, "TP"),
        execution("opposite", "SHORT", 1, 100, ".1", 11, 650, "CLOSE"),
    ]
    orders = [
        order("injection", purpose="RECOVERY"),
        order("mixed", purpose="CLOSE", reduce_only=True),
        old_tp,
        order("unrelated", purpose="TP", reduce_only=True, parent="foreign"),
        order("opposite", "SHORT", "CLOSE", True),
    ]
    assert recovery_exit_budget(info, ledger, orders, []) == D(".2") + D(".3") + D(".3") - 5


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_recovery_exit_budget_signed_rebates_and_funding_keep_economic_sign(side):
    info = {**membership(side.value, ["member"], "-.12"), "injection_id": "injection"}
    ledger = [
        # Injection identity ties its entry fee to this activation even when an
        # exchange timestamp differs slightly from the local activation clock.
        execution("injection", side, 1, 100, "-.08", 0, 399, "RECOVERY"),
        execution("member-tp", side, 1, 90, "-.03", "-2", 400, "TP"),
        execution("before", side, 1, 90, ".09", 10, 399, "TP"),
    ]
    orders = [
        order("injection", side.value, "RECOVERY"),
        order("member-tp", side.value, "TP", True, "member"),
        order("before", side.value, "TP", True, "member"),
    ]
    other = Side.SHORT if side == Side.LONG else Side.LONG
    funding = [
        {"side": side.value, "amount": ".2", "time_ms": "400"},
        {"side": side.value, "amount": "-.07", "time_ms": "450"},
        {"side": side.value, "amount": "50", "time_ms": "399"},
        {"side": other.value, "amount": "80", "time_ms": "500"},
    ]
    assert recovery_exit_budget(info, ledger, orders, funding) == D("1.64")


def test_recovery_exit_budget_aggregate_tp_requires_current_block_identity():
    info = {**membership("SHORT", ["member"], ".1"), "injection_id": "injection"}
    tp = order("tp", "SHORT", "RECOVERY_TP", True)
    tp["pair_id"] = "injection"
    ledger = [execution("tp", "SHORT", 1, 90, ".09", 10, 600, "RECOVERY_TP")]
    assert recovery_exit_budget(info, ledger, [tp], []) == D("-9.81")


def test_recovery_exit_budget_fee_allocation_remainder_matches_portfolio_exactly():
    info = {**membership("LONG", ["member"], "0"), "injection_id": "injection"}
    allocations = [
        {"link_id": "foreign-one", "qty": "1", "realized_pnl": "0"},
        {"link_id": "foreign-two", "qty": "1", "realized_pnl": "0"},
        {"link_id": "member", "qty": "1", "realized_pnl": "0"},
    ]
    ledger = [execution("close", "LONG", 3, 100, 1, 0, 600, "CLOSE", allocations)]
    orders = [order("close", purpose="CLOSE", reduce_only=True)]
    budget = recovery_exit_budget(info, ledger, orders, [])
    portfolio = calculate_portfolio(ledger, [], [], orders, [info], D(100))
    assert budget == 1 - 2 * (D(1) / 3)
    assert budget == -portfolio["recovery"]


@pytest.mark.parametrize("amount", [".1", "-.1"])
def test_recovery_exit_budget_unknown_side_nonzero_post_activation_funding_fails_closed(amount):
    info = {**membership("LONG", ["member"], ".1"), "injection_id": "injection"}
    with pytest.raises(ValidationError, match="Funding senza lato"):
        recovery_exit_budget(info, [], [], [{"amount": amount, "time_ms": "400"}])
    assert recovery_exit_budget(
        info, [], [], [{"amount": "0", "time_ms": "400"}, {"amount": amount, "time_ms": "399"}]
    ) == D(".1")


@pytest.mark.parametrize(
    "allocations",
    [None, [{"link_id": "member", "qty": "1", "realized_pnl": "2"}]],
)
def test_recovery_exit_budget_unknown_or_inconsistent_aggregate_close_fails_closed(allocations):
    info = {**membership("LONG", ["member"], ".1"), "injection_id": "injection"}
    ledger = [execution("close", "LONG", 1, 90, ".09", 1, 600, "CLOSE", allocations)]
    with pytest.raises(ValidationError):
        recovery_exit_budget(info, ledger, [order("close", purpose="CLOSE", reduce_only=True)], [])


async def eventually_async(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while not await predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timeout waiting for confirmed local-server ledger")
        await asyncio.sleep(0.02)


async def prepare_losing_lot(runtime, server, side, config=None):
    await runtime.initialize()
    await runtime.connect(Environment.DEMO)
    await wait_for(lambda: runtime.public_connected and runtime.private_connected)
    await runtime.configure(
        config
        or StrategyConfig(
            initial_pair=False,
            levels=1,
            recovery_profit_target_usdt=D(".2"),
        )
    )
    await runtime.start()
    opening = OrderIntent(
        environment=Environment.DEMO,
        symbol="BTCUSDT",
        order_link_id="independent-grid-entry",
        side=side,
        qty=D(".001"),
        purpose="GRID",
    )
    await runtime.manager.submit(opening)

    async def filled():
        return len(await runtime.store.lots()) == 1 and len(await runtime.store.orders()) == 2

    await eventually_async(filled)
    await runtime.pause()
    await server.state.advance_market(D(64000) if side == Side.LONG else D(70000))
    await wait_for(lambda: runtime.price == server.state.price)
    await runtime.start()
    assert runtime.status == "RUNNING", runtime.error
    return opening


@pytest.mark.asyncio
@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
async def test_manual_recovery_real_runtime_local_http_ws_roundtrip_and_net_profit(
    local_bybit_server, tmp_path, side
):
    server = local_bybit_server
    runtime = make_runtime(tmp_path, server)
    try:
        opening = await prepare_losing_lot(runtime, server, side)
        before = len(server.state.orders)
        await runtime.inject(side, True)

        async def injection_filled():
            return len(await runtime.store.executions()) >= 2

        await eventually_async(injection_filled)
        assert (
            len([row for row in await runtime.store.orders() if row["purpose"] == "RECOVERY"]) == 1
        )
        async with runtime.lock:
            await runtime._recovery_protection()
        orders = await runtime.store.orders()
        tp = next(
            row
            for row in orders
            if row["purpose"] == "RECOVERY_TP" and row["state"] not in {"FILLED", "CANCELED"}
        )
        assert len(server.state.orders) > before
        assert D(tp["qty"]) == sum((D(lot["qty"]) for lot in await runtime.store.lots()), D(0))
        assert all(row["state"] == "CANCELED" for row in orders if row["purpose"] == "TP")
        # The temporary injection tranche TP has been intentionally canceled in
        # favor of the block TP; periodic protection must recognize the handoff.
        await runtime.manager.ensure_protection(runtime.active_recovery)
        lots = await runtime.store.lots()
        qty = sum((D(lot["qty"]) for lot in lots), D(0))
        cost = sum((D(lot["qty"]) * D(lot["entry"]) for lot in lots), D(0))
        entry_fees = sum((D(lot["fees"]) for lot in lots), D(0))
        slip = runtime.config.slippage_pct / 100
        quoted = D(tp["price"])
        adverse_exit = quoted * (1 - slip if side == Side.LONG else 1 + slip)
        gross = (qty * adverse_exit - cost) * (1 if side == Side.LONG else -1)
        independently_net = gross - entry_fees - qty * adverse_exit * runtime.account.taker_fee
        assert independently_net >= runtime.config.recovery_profit_target_usdt - D("1e-20")
        # Actual exchange execution respects the submitted limit, unlike the adverse
        # modeled exit used above solely to verify the TP arithmetic independently.
        await runtime.pause()
        await server.state.fill(tp["order_id"], price=quoted)

        async def closed():
            return not await runtime.store.lots()

        await eventually_async(closed)
        async with runtime.lock:
            await runtime._recovery_protection()
        assert side.value not in runtime.active_recovery
        cash = await runtime.portfolio()
        assert D(cash["net"]) >= runtime.config.recovery_profit_target_usdt
        assert abs(D(cash["recovery"]) - D(cash["net"])) < D("1e-20")
        assert abs(D(cash["grid"])) < D("1e-20")
        created = len(server.state.orders)
        await runtime.shutdown()
        runtime = make_runtime(tmp_path, server)
        await runtime.initialize()
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.private_connected and runtime.public_connected)
        assert len(server.state.orders) == created
        reconstructed = await runtime.portfolio()
        assert reconstructed["net"] == cash["net"]
        assert reconstructed["recovery"] == cash["recovery"]
        assert opening.order_link_id not in [
            row["order_link_id"] for row in await runtime.store.lots()
        ]
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_manual_recovery_static_max_injection_blocks_before_exchange_mutation(
    local_bybit_server, tmp_path
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    try:
        await prepare_losing_lot(
            runtime,
            local_bybit_server,
            Side.LONG,
            StrategyConfig(
                initial_pair=False,
                levels=1,
                recovery_profit_target_usdt=D(".2"),
                max_injection_usdt=D(1),
            ),
        )
        before = len(local_bybit_server.state.orders)
        plans = await runtime.recovery_plans()
        assert plans[0]["safe"] is False
        with pytest.raises(RecoveryError, match="NON SICURO"):
            await runtime.inject(Side.LONG, True)
        assert len(local_bybit_server.state.orders) == before
        assert not runtime.active_recovery
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
async def test_manual_recovery_dynamic_available_margin_blocks_mathematically_feasible_plan(
    local_bybit_server, tmp_path, side
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    try:
        await prepare_losing_lot(runtime, local_bybit_server, side)
        assert (await runtime.recovery_plans())[0]["safe"] is True
        # Change the authoritative exchange balance, then wait for the real wallet
        # stream/REST refresh. Mutating only the runtime cache races with queued
        # wallet events from the earlier fill and can restore the original balance.
        local_bybit_server.state.available_balance = D(0)
        await local_bybit_server.state.broadcast("wallet", [local_bybit_server.state.wallet()])
        await wait_for(lambda: runtime.account.available_balance == D(0))
        before = len(local_bybit_server.state.orders)
        with pytest.raises(RiskError, match="Saldo"):
            await runtime.inject(side, True)
        assert len(local_bybit_server.state.orders) == before
        assert not runtime.active_recovery
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "total_cap,recovery_cap,reason",
    [
        (D(1000), D(350), "Recovery Exposure"),
        (D(350), D(350), "Total Exposure"),
    ],
)
async def test_manual_recovery_static_exposure_caps_are_checked_before_sending(
    local_bybit_server,
    tmp_path,
    total_cap,
    recovery_cap,
    reason,
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    try:
        await prepare_losing_lot(
            runtime,
            local_bybit_server,
            Side.SHORT,
            StrategyConfig(
                initial_pair=False,
                levels=1,
                recovery_profit_target_usdt=D(".2"),
                max_exposure_usdt=total_cap,
                max_recovery_exposure_usdt=recovery_cap,
            ),
        )
        plan = (await runtime.recovery_plans())[0]
        assert plan["safe"] is False
        assert reason in plan["reason"]
        before = len(local_bybit_server.state.orders)
        with pytest.raises(RecoveryError, match="NON SICURO"):
            await runtime.inject(Side.SHORT, True)
        assert len(local_bybit_server.state.orders) == before
        assert not runtime.active_recovery
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_manual_recovery_dynamic_pending_order_reservations_block_static_safe_plan(
    local_bybit_server,
    tmp_path,
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    try:
        await prepare_losing_lot(
            runtime,
            local_bybit_server,
            Side.SHORT,
            StrategyConfig(
                initial_pair=False,
                levels=1,
                recovery_profit_target_usdt=D(".2"),
                max_exposure_usdt=D(800),
                max_recovery_exposure_usdt=D(800),
            ),
        )
        assert (await runtime.recovery_plans())[0]["safe"] is True
        for index in range(4):
            pending = OrderIntent(
                environment=Environment.DEMO,
                symbol="BTCUSDT",
                order_link_id=f"independent-pending-{index}",
                side=Side.SHORT,
                qty=D(".001"),
                price=D(80000),
                order_type="Limit",
                purpose="GRID",
            )
            await runtime.manager.submit(pending)
        probe = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="independent-risk-probe",
            side=Side.SHORT,
            qty=D(".006"),
            purpose="RECOVERY",
        )
        context = await runtime.risk_context(probe)
        assert context.reserved_notional == D(320)
        before = len(local_bybit_server.state.orders)
        with pytest.raises(RiskError, match="Total Exposure"):
            runtime.manager.risk.validate_order(probe, context, runtime.config, runtime.instrument)
        # The runtime adds an earlier protection: original entries must be terminal
        # so a late fill cannot change recovery membership after activation.
        with pytest.raises(RecoveryError, match="conferma di tutti gli ingressi"):
            await runtime.inject(Side.SHORT, True)
        assert len(local_bybit_server.state.orders) == before
        assert not runtime.active_recovery
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_active_recovery_below_threshold_survives_restart_without_duplicate_or_false_tp_alarm(
    local_bybit_server,
    tmp_path,
):
    server = local_bybit_server
    runtime = make_runtime(tmp_path, server)
    try:
        await prepare_losing_lot(runtime, server, Side.SHORT)
        await runtime.inject(Side.SHORT, True)

        async def filled():
            return len(await runtime.store.executions()) == 2

        await eventually_async(filled)
        async with runtime.lock:
            await runtime._recovery_protection()
        current = await runtime.state()
        block = next(row for row in current["recovery"] if row["side"] == "SHORT")
        assert block["active"] is True
        assert (
            abs(D(block["average"]) - runtime.price) / D(block["average"]) * 100
            < runtime.config.recovery_threshold_pct
        )
        await runtime.pause()
        created = len(server.state.orders)
        await runtime.shutdown()
        runtime = make_runtime(tmp_path, server)
        await runtime.initialize()
        assert runtime.status == "DISCONNECTED"
        await runtime.connect(Environment.DEMO)
        await wait_for(lambda: runtime.public_connected and runtime.private_connected)
        current = await runtime.state()
        recovered = next(row for row in current["recovery"] if row["side"] == "SHORT")
        assert recovered["active"] is True and recovered["tp"] == block["tp"]
        assert recovered["progress"] is not None
        await runtime.start()
        await runtime.manager.ensure_protection(runtime.active_recovery)
        assert runtime.status == "RUNNING", runtime.error
        assert len(server.state.orders) == created
        assert "SHORT" in runtime.active_recovery
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_canceled_recovery_tp_repair_uses_new_persisted_generation_without_duplicates(
    local_bybit_server,
    tmp_path,
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    try:
        await prepare_losing_lot(runtime, local_bybit_server, Side.LONG)
        await runtime.inject(Side.LONG, True)

        async def filled():
            return len(await runtime.store.executions()) == 2

        await eventually_async(filled)
        async with runtime.lock:
            await runtime._recovery_protection()
            tp = next(
                row for row in await runtime.store.orders() if row["purpose"] == "RECOVERY_TP"
            )
            old_generation = runtime.recovery_info["LONG"].get("tp_generation", 0)
            await runtime.manager.cancel(tp)
            before = len(local_bybit_server.state.orders)
            await runtime._recovery_protection()
            repaired = next(
                row
                for row in await runtime.store.orders()
                if row["purpose"] == "RECOVERY_TP"
                and row["state"] not in {"CANCELED", "FILLED", "REJECTED"}
            )
            assert repaired["order_link_id"] != tp["order_link_id"]
            assert D(repaired["qty"]) == sum(
                (D(lot["qty"]) for lot in await runtime.store.lots()), D(0)
            )
            assert len(local_bybit_server.state.orders) == before + 1
            assert runtime.recovery_info["LONG"]["tp_generation"] == old_generation + 1
            persisted = await runtime.store.get("recovery_blocks", "active")
            assert persisted["info"]["LONG"]["tp_generation"] == old_generation + 1
            await runtime._recovery_protection()
            await runtime.manager.ensure_protection(runtime.active_recovery)
            assert len(local_bybit_server.state.orders) == before + 1
        assert await runtime.store.lots()
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_recovery_tp_partial_execution_keeps_exact_remaining_coverage_without_new_injection(
    local_bybit_server,
    tmp_path,
):
    runtime = make_runtime(tmp_path, local_bybit_server)
    try:
        await prepare_losing_lot(runtime, local_bybit_server, Side.LONG)
        await runtime.inject(Side.LONG, True)

        async def filled():
            return len(await runtime.store.executions()) == 2

        await eventually_async(filled)
        async with runtime.lock:
            await runtime._recovery_protection()
        tp = next(row for row in await runtime.store.orders() if row["purpose"] == "RECOVERY_TP")
        created = len(local_bybit_server.state.orders)
        original_generation = runtime.recovery_info["LONG"].get("tp_generation", 0)
        local_bybit_server.state.duplicate_executions = True
        await local_bybit_server.state.fill(tp["order_id"], qty=D(".002"), price=D(tp["price"]))

        async def partial_received():
            return len(await runtime.store.executions()) == 3

        await eventually_async(partial_received)
        first_partial = await runtime.store.get_order(tp["order_link_id"])
        assert D(first_partial["executed_qty"]) == D(".002")
        await local_bybit_server.state.fill(tp["order_id"], qty=D(".001"), price=D(tp["price"]))

        async def second_partial_received():
            return len(await runtime.store.executions()) == 4

        await eventually_async(second_partial_received)
        state = await runtime.state()
        assert D(state["portfolio"]["grid"]) == 0
        assert D(state["portfolio"]["recovery"]) == D(state["portfolio"]["net"])
        async with runtime.lock:
            for _ in range(3):
                await runtime._recovery_protection()
                await runtime.manager.ensure_protection(runtime.active_recovery)
        remaining_tp = await runtime.store.get_order(tp["order_link_id"])
        remaining_lots = await runtime.store.lots()
        assert D(remaining_tp["executed_qty"]) == D(".003")
        assert D(remaining_tp["qty"]) - D(remaining_tp["executed_qty"]) == sum(
            (D(row["qty"]) for row in remaining_lots), D(0)
        )
        assert runtime.recovery_info["LONG"].get("tp_generation", 0) == original_generation
        assert len(local_bybit_server.state.orders) == created
        assert (
            len([row for row in await runtime.store.orders() if row["purpose"] == "RECOVERY"]) == 1
        )
        assert runtime.status == "RUNNING", runtime.error
        assert "LONG" in runtime.active_recovery
    finally:
        await runtime.shutdown()
