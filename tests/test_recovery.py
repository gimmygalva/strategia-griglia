import random
from decimal import Decimal as D

import pytest
from gridbot.errors import RecoveryError
from gridbot.models import Instrument, Side, StrategyConfig
from gridbot.pnl import PnLEngine
from gridbot.recovery import InjectionCalculator, RecoveryEngine, break_even


def instrument() -> Instrument:
    return Instrument(
        symbol="BTCUSDT",
        tick_size=D(".1"),
        qty_step=D(".001"),
        min_qty=D(".001"),
        max_qty=D(100),
        max_market_qty=D(20),
        min_notional=D(5),
    )


def test_long_injection_algebra_independently_matches_target_average():
    plan = InjectionCalculator.calculate(Side.LONG, D(2), D(110), D(100), D(105), slippage=D(0))
    assert plan.required_qty == D(2)
    assert (D(2) * D(110) + plan.required_qty * D(100)) / (D(2) + plan.required_qty) == D(105)
    assert plan.required_usdt == D(200)


def test_short_injection_algebra_independently_matches_target_average():
    plan = InjectionCalculator.calculate(Side.SHORT, D(2), D(90), D(100), D(95), slippage=D(0))
    assert plan.required_qty == D(2)
    assert (D(2) * D(90) + plan.required_qty * D(100)) / (D(2) + plan.required_qty) == D(95)


@pytest.mark.parametrize(
    "side,average,target", [(Side.LONG, "110", "105"), (Side.SHORT, "90", "95")]
)
def test_injection_uses_adverse_effective_price(side, average, target):
    plan = InjectionCalculator.calculate(
        side, D(2), D(average), D(100), D(target), slippage=D(".01")
    )
    effective = D(101) if side == Side.LONG else D(99)
    assert plan.effective_price == effective
    assert plan.required_qty == D("2.5")
    assert plan.new_average == D(target)


@pytest.mark.parametrize(
    "side,average,target",
    [
        (Side.LONG, "110", "99"),
        (Side.LONG, "110", "100"),
        (Side.LONG, "110", "111"),
        (Side.SHORT, "90", "101"),
        (Side.SHORT, "90", "100"),
        (Side.SHORT, "90", "89"),
    ],
)
def test_infeasible_average_never_defaults_to_an_injection(side, average, target):
    with pytest.raises(RecoveryError):
        InjectionCalculator.calculate(side, D(2), D(average), D(100), D(target), slippage=D(0))


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
@pytest.mark.parametrize("profit", [D(0), D("3.75")])
def test_break_even_by_independent_net_pnl_substitution(side, profit):
    qty, entry, fees, rate, slip = D("1.37"), D("100.25"), D(".29"), D(".0008"), D(".002")
    exit_quote = break_even(side, qty, entry, fees, rate, slip, profit)
    actual_exit = exit_quote * (1 - slip if side == Side.LONG else 1 + slip)
    gross = qty * (actual_exit - entry) * (1 if side == Side.LONG else -1)
    independently_net = gross - fees - qty * actual_exit * rate
    assert abs(independently_net - profit) < D("1e-23")


def test_short_break_even_impossible_profit_fails():
    with pytest.raises(RecoveryError):
        break_even(Side.SHORT, D(1), D(100), D(101), D(".001"), D(".001"))


@pytest.mark.parametrize(
    "side,avg,exit_quote", [(Side.LONG, D(110), D(102)), (Side.SHORT, D(90), D(98))]
)
def test_exit_based_injection_ceil_qty_independently_meets_net_target(side, avg, exit_quote):
    q, market, entry_fees, rate, slip, profit = D(1), D(100), D(".07"), D(".0006"), D(".001"), D(1)
    plan = InjectionCalculator.for_exit(
        side, q, avg, market, exit_quote, instrument(), entry_fees, rate, slip, profit
    )
    assert plan.required_qty % instrument().qty_step == 0
    effective_exit = exit_quote * (1 - slip if side == Side.LONG else 1 + slip)
    effective_entry = market * (1 + slip if side == Side.LONG else 1 - slip)
    existing_gross = q * (effective_exit - avg) * (1 if side == Side.LONG else -1)
    injection_gross = (
        plan.required_qty * (effective_exit - effective_entry) * (1 if side == Side.LONG else -1)
    )
    new_entry_fee = plan.required_qty * effective_entry * rate
    exit_fee = (q + plan.required_qty) * effective_exit * rate
    independent_net = existing_gross + injection_gross - entry_fees - new_entry_fee - exit_fee
    assert independent_net >= profit - D("1e-23")
    smaller = plan.required_qty - instrument().qty_step
    smaller_net = existing_gross + smaller * (effective_exit - effective_entry) * (
        1 if side == Side.LONG else -1
    )
    smaller_net -= (
        entry_fees + smaller * effective_entry * rate + (q + smaller) * effective_exit * rate
    )
    assert smaller_net < profit


def test_retrace_cannot_cover_fees_never_injects():
    with pytest.raises(RecoveryError, match="fee/slippage"):
        InjectionCalculator.for_exit(
            Side.LONG, D(1), D(110), D(100), D("100.1"), instrument(), slippage=D(".001")
        )


def test_recovery_empty_or_profitable_is_not_necessary():
    engine = RecoveryEngine()
    assert engine.analyze([], D(100), StrategyConfig(), instrument()) == []
    assert (
        engine.analyze(
            [{"side": "LONG", "qty": "1", "entry": "90"}], D(100), StrategyConfig(), instrument()
        )
        == []
    )


def test_recovery_threshold_and_separate_long_short_executed_blocks():
    lots = [
        {"side": "LONG", "qty": ".1", "entry": "110", "fees": ".01", "order_link_id": "long1"},
        {"side": "LONG", "qty": ".2", "entry": "105", "fees": ".02", "order_link_id": "long2"},
        {"side": "SHORT", "qty": ".1", "entry": "90", "fees": ".01", "order_link_id": "short1"},
    ]
    blocks = RecoveryEngine().analyze(lots, D(100), StrategyConfig(), instrument())
    assert len(blocks) == 2
    long, short = blocks
    assert long["side"] == "LONG" and short["side"] == "SHORT"
    assert D(long["qty"]) == D(".3")
    assert abs(D(long["average"]) - D(320) / 3) < D("1e-24")
    assert D(short["average"]) == D(90)
    assert long["lot_ids"] == ["long1", "long2"]
    assert long["progress"] is None  # A baseline has not yet been persisted.
    assert long["risk_validation_required"] is True


def test_partial_fill_recovery_ignores_requested_pending_qty():
    blocks = RecoveryEngine().analyze(
        [{"side": "LONG", "qty": "4", "requested_qty": "10", "entry": "110", "fees": ".1"}],
        D(100),
        StrategyConfig(),
        instrument(),
    )
    assert D(blocks[0]["qty"]) == D(4)
    assert D(blocks[0]["notional"]) == D(440)


def test_max_injection_limit_returns_visible_unsafe_plan():
    blocks = RecoveryEngine().analyze(
        [{"side": "LONG", "qty": "1", "entry": "110"}],
        D(100),
        StrategyConfig(max_injection_usdt=D(20)),
        instrument(),
    )
    assert blocks[0]["safe"] is False
    assert "Max Injection" in blocks[0]["reason"]
    assert D(blocks[0]["required_usdt"]) > 20


def test_recovery_exposure_limit_rejects_even_small_individual_injection():
    config = StrategyConfig(
        max_injection_usdt=D(100000), max_recovery_exposure_usdt=D(100), max_exposure_usdt=D(100000)
    )
    blocks = RecoveryEngine().analyze(
        [{"side": "SHORT", "qty": "1", "entry": "90"}], D(100), config, instrument()
    )
    assert blocks[0]["safe"] is False
    assert "Recovery Exposure" in blocks[0]["reason"]


def test_recovery_exposure_counts_both_losing_hedge_sides():
    config = StrategyConfig(
        max_injection_usdt=D(100000),
        max_recovery_exposure_usdt=D(2600),
        max_exposure_usdt=D(100000),
    )
    lots = [
        {"side": "LONG", "qty": "1", "entry": "104"},
        {"side": "SHORT", "qty": "22", "entry": "90"},
    ]
    blocks = RecoveryEngine().analyze(lots, D(100), config, instrument())
    assert blocks[0]["safe"] is False
    assert "Recovery Exposure" in blocks[0]["reason"]


def test_total_exposure_counts_both_sides():
    config = StrategyConfig(
        max_injection_usdt=D(100000),
        max_recovery_exposure_usdt=D(100000),
        max_exposure_usdt=D(100000),
    )
    lots = [
        {"side": "LONG", "qty": "1", "entry": "110"},
        {"side": "SHORT", "qty": "998", "entry": "110"},
    ]
    blocks = RecoveryEngine().analyze(lots, D(100), config, instrument())
    assert blocks[0]["safe"] is False
    assert "Total Exposure" in blocks[0]["reason"]


def test_invalid_lot_is_not_silently_ignored():
    with pytest.raises(RecoveryError):
        RecoveryEngine().analyze(
            [{"side": "LONG", "qty": "-1", "entry": "110"}], D(100), StrategyConfig(), instrument()
        )


def test_net_pnl_distinguishes_fees_and_funding():
    result = PnLEngine.realized(Side.LONG, D(2), D(100), D(105), D(".1"), D(".2"), D("-.05"))
    assert result == {"realized": D(10), "fees": D(".3"), "funding": D("-.05"), "net": D("9.65")}


def test_signed_actual_rebate_preserves_fee_accounting_and_recovery():
    accounting = PnLEngine.realized(Side.SHORT, D(1), D(100), D(90), D("-.01"), D(".02"))
    assert accounting["fees"] == D(".01")
    assert accounting["net"] == D("9.99")
    blocks = RecoveryEngine().analyze(
        [{"side": "LONG", "qty": ".1", "entry": "110", "fees": "-.01"}],
        D(100),
        StrategyConfig(),
        instrument(),
    )
    assert D(blocks[0]["fees"]) == D("-.01")
    assert blocks[0]["required_qty"] is not None


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_seeded_recovery_sweep_meets_independent_net_profit_target(side):
    source = random.Random(84722)
    for _ in range(200):
        market = D(source.randint(100, 80000))
        qty = D(source.randint(5, 80)) / 1000
        adverse = D(source.randint(4, 12)) / 100
        average = market * (1 + adverse if side == Side.LONG else 1 - adverse)
        exit_quote = market * (D("1.02") if side == Side.LONG else D(".98"))
        fees = qty * average * D(".0003")
        target = D(".13")
        plan = InjectionCalculator.for_exit(
            side,
            qty,
            average,
            market,
            exit_quote,
            instrument(),
            fees,
            D(".0006"),
            D(".001"),
            target,
        )
        actual_exit = exit_quote * (D(".999") if side == Side.LONG else D("1.001"))
        gross = qty * (actual_exit - average) + plan.required_qty * (
            actual_exit - plan.effective_price
        )
        gross *= 1 if side == Side.LONG else -1
        costs = fees + plan.required_qty * plan.effective_price * D(".0006")
        costs += (qty + plan.required_qty) * actual_exit * D(".0006")
        assert gross - costs >= target - D("1e-18")
