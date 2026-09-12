from decimal import Decimal as D

import pytest
from gridbot.errors import RiskError
from gridbot.models import Environment, Instrument, OrderIntent, RiskContext, Side, StrategyConfig
from gridbot.risk import RiskEngine


def instrument(**changes) -> Instrument:
    values = {
        "symbol": "BTCUSDT",
        "tick_size": D(".1"),
        "qty_step": D(".001"),
        "min_qty": D(".001"),
        "max_qty": D(10),
        "max_market_qty": D(2),
        "min_notional": D(5),
        "max_leverage": D(3),
    }
    return Instrument(**{**values, **changes})


def context(**changes) -> RiskContext:
    values = {
        "environment": Environment.DEMO,
        "connected": True,
        "running": True,
        "reconciled": True,
        "permissions": True,
        "hedge_mode": True,
        "available_balance": D(1000),
        "total_exposure": D(0),
        "recovery_exposure": D(0),
        "daily_pnl": D(0),
        "market_price": D(100),
        "position_qty": D(1),
    }
    return RiskContext(**{**values, **changes})


def intent(**changes) -> OrderIntent:
    values = {
        "environment": Environment.DEMO,
        "symbol": "BTCUSDT",
        "order_link_id": "ghb-unique-1",
        "side": Side.LONG,
        "qty": D(".1"),
    }
    return OrderIntent(**{**values, **changes})


def validate(order=None, ctx=None, config=None, rule=None):
    RiskEngine.validate_order(
        order or intent(), ctx or context(), config or StrategyConfig(), rule or instrument()
    )


def test_safe_demo_opening_order():
    validate()


@pytest.mark.parametrize(
    "changes",
    [
        {"connected": False},
        {"running": False},
        {"reconciled": False},
        {"permissions": False},
        {"hedge_mode": False},
        {"duplicate": True},
        {"available_balance": D(1)},
        {"daily_pnl": D(-100)},
        {"daily_pnl": D(-101)},
        {"total_exposure": D(5000)},
        {"reserved_notional": D(5000)},
        {"total_exposure": D(-1)},
        {"reserved_notional": D(-1)},
        {"market_price": D(0)},
    ],
)
def test_unsafe_context_rejects_opening(changes):
    with pytest.raises(RiskError):
        validate(ctx=context(**changes))


def test_demo_credentials_context_cannot_open_mainnet():
    with pytest.raises(RiskError, match="Environment"):
        validate(order=intent(environment=Environment.MAINNET))


@pytest.mark.parametrize("backend_flag,ui_flag", [(False, False), (True, False), (False, True)])
def test_live_requires_both_backend_and_ui_flags(backend_flag, ui_flag):
    with pytest.raises(RiskError, match="LIVE"):
        validate(
            order=intent(environment=Environment.MAINNET),
            ctx=context(
                environment=Environment.MAINNET,
                mainnet_allowed=backend_flag,
                live_confirmed=ui_flag,
            ),
        )


def test_live_both_flags_same_strategy_logic():
    validate(
        order=intent(environment=Environment.MAINNET),
        ctx=context(environment=Environment.MAINNET, mainnet_allowed=True, live_confirmed=True),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "ETHUSDT"},
        {"qty": D(".1005")},
        {"qty": D(".0001")},
        {"qty": D(3)},
        {"qty": D("1.001")},
        {"qty": D(".01")},
        {"order_type": "Stop"},
        {"order_type": "Limit"},
        {"order_type": "Market", "price": D(100)},
        {"order_type": "Limit", "price": D("100.05")},
        {"purpose": "UNKNOWN"},
        {"slippage_pct": D(1)},
    ],
)
def test_invalid_order_or_instrument_amount_rejected(changes):
    with pytest.raises(RiskError):
        validate(order=intent(**changes))


def test_min_notional_limit_buy_uses_capped_price():
    order = intent(qty=D(".1"), price=D(900), order_type="Limit")
    with pytest.raises(RiskError, match="Notional"):
        validate(order=order, rule=instrument(min_notional=D(50)))


def test_nontrading_symbol_rejected():
    with pytest.raises(RiskError):
        validate(rule=instrument(status="PreLaunch"))


def test_config_leverage_must_fit_instrument():
    with pytest.raises(RiskError, match="Leverage"):
        validate(config=StrategyConfig(leverage=D(2)), rule=instrument(max_leverage=D(1)))


def test_reserved_orders_consume_margin_before_fill():
    validate(ctx=context(available_balance=D(20)))
    with pytest.raises(RiskError, match="riservati"):
        validate(ctx=context(available_balance=D(20), reserved_notional=D(15)))


def test_fees_and_slippage_reserved_at_one_times_leverage():
    with pytest.raises(RiskError, match="Saldo"):
        validate(ctx=context(available_balance=D(10)))
    validate(ctx=context(available_balance=D("10.023")))


def test_recovery_max_injection_is_checked():
    with pytest.raises(RiskError, match="Injection"):
        validate(
            order=intent(purpose="RECOVERY", qty=D(1)),
            config=StrategyConfig(max_injection_usdt=D(90)),
        )


def test_recovery_exposure_and_pending_reservations_are_checked():
    with pytest.raises(RiskError, match="Recovery Exposure"):
        validate(order=intent(purpose="RECOVERY"), ctx=context(recovery_exposure=D(1990)))


def test_reduce_only_allowed_when_paused_daily_loss_reached_and_no_free_margin():
    validate(
        order=intent(reduce_only=True, purpose="TP"),
        ctx=context(
            running=False, daily_pnl=D(-1000), available_balance=D(0), total_exposure=D(6000)
        ),
    )


def test_reduce_only_min_notional_exemption_still_respects_min_qty():
    validate(
        order=intent(reduce_only=True, purpose="CLOSE", qty=D(".001")), ctx=context(running=False)
    )
    with pytest.raises(RiskError, match="Qty"):
        validate(
            order=intent(reduce_only=True, purpose="CLOSE", qty=D(".0001")),
            ctx=context(running=False),
        )


def test_reduce_only_cannot_close_unowned_qty():
    with pytest.raises(RiskError, match="proprietà"):
        validate(
            order=intent(reduce_only=True, purpose="TP", qty=D(".2")),
            ctx=context(position_qty=D(".1")),
        )


def test_reduce_only_needs_known_connected_state():
    with pytest.raises(RiskError):
        validate(
            order=intent(reduce_only=True, purpose="CLOSE"),
            ctx=context(reconciled=False, running=False),
        )


def test_reduce_only_explicit_purpose_required():
    with pytest.raises(RiskError):
        validate(order=intent(reduce_only=True))


def test_reduce_only_side_maps_to_distinct_hedge_indices():
    long = intent(reduce_only=True, purpose="TP", side=Side.LONG)
    short = intent(reduce_only=True, purpose="TP", side=Side.SHORT)
    validate(order=long)
    validate(order=short)
    assert (long.side.position_idx, long.side.closing_side) == (1, "Sell")
    assert (short.side.position_idx, short.side.closing_side) == (2, "Buy")


def test_validate_order_alias_has_same_fail_closed_behavior():
    with pytest.raises(RiskError):
        RiskEngine.validateOrder(intent(), context(connected=False), StrategyConfig(), instrument())
