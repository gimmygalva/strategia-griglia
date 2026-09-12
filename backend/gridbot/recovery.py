"""Executed-lot recovery arithmetic including fees and adverse execution slippage."""

from decimal import Decimal

from .errors import RecoveryError, ValidationError
from .grid import decimal_value, round_down, round_up, weighted_average
from .models import InjectionPlan, Instrument, Side, StrategyConfig

ZERO = Decimal("0")
ONE = Decimal("1")


def _inputs(
    qty: Decimal,
    average: Decimal,
    fees: Decimal,
    fee_rate: Decimal,
    slippage: Decimal,
    profit_target: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    try:
        values = tuple(
            decimal_value(value)
            for value in (qty, average, fees, fee_rate, slippage, profit_target)
        )
    except ValidationError as exc:
        raise RecoveryError(str(exc)) from exc
    q, a, f, r, s, p = values
    # Actual execution fees may be negative (confirmed maker rebates). Estimated
    # future fee rates remain nonnegative for conservative risk decisions.
    if q <= 0 or a <= 0 or p < 0 or not 0 <= r < 1 or not 0 <= s < 1:
        raise RecoveryError("Input Recovery non valido")
    return q, a, f, r, s, p


def break_even(
    side: Side,
    qty: Decimal,
    average: Decimal,
    fees: Decimal,
    exit_fee_rate: Decimal,
    exit_slippage: Decimal,
    profit_target: Decimal = ZERO,
) -> Decimal:
    """Required quoted exit price for net PnL == profit_target.

    LONG: (Q*A + F + profit) / [Q*(1-slippage)*(1-exit_fee)]
    SHORT: (Q*A - F - profit) / [Q*(1+slippage)*(1+exit_fee)]
    F is actual paid entry fees (including injection fees), excluding future exits.
    """
    side = Side(side)
    q, a, f, rate, slip, target = _inputs(
        qty, average, fees, exit_fee_rate, exit_slippage, profit_target
    )
    if side == Side.LONG:
        numerator = q * a + f + target
        if numerator <= 0:
            raise RecoveryError("Nessun exit price LONG positivo corrisponde al target netto")
        return numerator / (q * (ONE - slip) * (ONE - rate))
    numerator = q * a - f - target
    if numerator <= 0:
        raise RecoveryError("Nessun exit price SHORT positivo raggiunge il target netto")
    return numerator / (q * (ONE + slip) * (ONE + rate))


class InjectionCalculator:
    @staticmethod
    def calculate(
        side: Side,
        current_qty: Decimal,
        average: Decimal,
        market: Decimal,
        target_average: Decimal,
        entry_fees: Decimal = ZERO,
        fee_rate: Decimal = Decimal("0.0006"),
        slippage: Decimal = Decimal("0.001"),
        profit_target: Decimal = ZERO,
    ) -> InjectionPlan:
        side = Side(side)
        q, a, fees, rate, slip, profit = _inputs(
            current_qty, average, entry_fees, fee_rate, slippage, profit_target
        )
        try:
            market, target = decimal_value(market), decimal_value(target_average)
        except ValidationError as exc:
            raise RecoveryError(str(exc)) from exc
        if market <= 0 or target <= 0:
            raise RecoveryError("Market/target average non positivi")
        effective = market * (ONE + slip if side == Side.LONG else ONE - slip)
        feasible = effective < target < a if side == Side.LONG else a < target < effective
        if not feasible:
            raise RecoveryError("Target average non raggiungibile al prezzo effettivo modellato")
        # T(Q+x)=QA+xE => x=Q(A-T)/(T-E). No requested/unfilled quantity.
        additional = q * (a - target) / (target - effective)
        return InjectionCalculator._plan(
            side, q, a, effective, additional, target, fees, rate, slip, profit
        )

    @staticmethod
    def _plan(
        side: Side,
        qty: Decimal,
        average: Decimal,
        effective: Decimal,
        additional: Decimal,
        target: Decimal,
        entry_fees: Decimal,
        rate: Decimal,
        slip: Decimal,
        profit: Decimal,
    ) -> InjectionPlan:
        new_qty = qty + additional
        new_average = (qty * average + additional * effective) / new_qty
        total_entry_fees = entry_fees + additional * effective * rate
        required_exit = break_even(side, new_qty, new_average, total_entry_fees, rate, slip, profit)
        effective_exit = required_exit * (ONE - slip if side == Side.LONG else ONE + slip)
        total_estimated_fees = total_entry_fees + new_qty * effective_exit * rate
        return InjectionPlan(
            side=side,
            required_qty=additional,
            required_usdt=additional * effective,
            new_average=new_average,
            break_even=required_exit,
            target_average=target,
            estimated_fees=total_estimated_fees,
            effective_price=effective,
            profit_target=profit,
        )

    @staticmethod
    def for_exit(
        side: Side,
        current_qty: Decimal,
        average: Decimal,
        market: Decimal,
        exit_quote: Decimal,
        instrument: Instrument,
        entry_fees: Decimal = ZERO,
        fee_rate: Decimal = Decimal("0.0006"),
        slippage: Decimal = Decimal("0.001"),
        profit_target: Decimal = ZERO,
    ) -> InjectionPlan:
        """Solve net PnL at an explicit exit quote, then ceil to the instrument step.

        Buying/selling extra quantity can help only if that extra unit has positive
        net return at the modeled exit, after both fees and both slippage legs.
        """
        side = Side(side)
        q, a, fees, rate, slip, profit = _inputs(
            current_qty, average, entry_fees, fee_rate, slippage, profit_target
        )
        try:
            market, exit_quote = decimal_value(market), decimal_value(exit_quote)
        except ValidationError as exc:
            raise RecoveryError(str(exc)) from exc
        if market <= 0 or exit_quote <= 0:
            raise RecoveryError("Market/exit quote non positivi")
        if side == Side.LONG:
            entry = market * (ONE + slip)
            exit_price = exit_quote * (ONE - slip)
            unit_gain = exit_price * (ONE - rate) - entry * (ONE + rate)
            numerator = profit + fees + q * (a - exit_price * (ONE - rate))
        else:
            entry = market * (ONE - slip)
            exit_price = exit_quote * (ONE + slip)
            unit_gain = entry * (ONE - rate) - exit_price * (ONE + rate)
            numerator = profit + fees + q * (exit_price * (ONE + rate) - a)
        if unit_gain <= 0:
            raise RecoveryError("Retrace insufficiente per coprire fee/slippage dell'injection")
        if numerator <= 0:
            raise RecoveryError("Target già raggiungibile senza injection")
        additional = round_up(numerator / unit_gain, instrument.qty_step)
        additional = max(additional, round_up(instrument.min_qty, instrument.qty_step))
        target_average = (q * a + additional * entry) / (q + additional)
        return InjectionCalculator._plan(
            side, q, a, entry, additional, target_average, fees, rate, slip, profit
        )


class RecoveryEngine:
    def __init__(self, fee_rate: Decimal = Decimal("0.0006")) -> None:
        self.fee_rate = decimal_value(fee_rate, "fee rate")
        if not 0 <= self.fee_rate < 1:
            raise RecoveryError("Fee rate non valida")

    def analyze(
        self, lots: list[dict], market: Decimal, config: StrategyConfig, instrument: Instrument
    ) -> list[dict]:
        market = decimal_value(market, "market")
        if market <= 0 or instrument.symbol != config.symbol:
            raise RecoveryError("Market/instrument Recovery non valido")
        grouped: dict[Side, list[dict]] = {side: [] for side in Side}
        for lot in lots:
            try:
                side = Side(lot["side"])
                qty = decimal_value(lot["qty"])
                entry = decimal_value(lot["entry"])
                fees = decimal_value(lot.get("fees", "0"))
            except (KeyError, ValueError, ValidationError) as exc:
                raise RecoveryError("Lotto Recovery non valido") from exc
            if qty < 0 or entry <= 0:
                raise RecoveryError("Lotto Recovery con quantità/prezzo/fee non valido")
            if qty:
                grouped[side].append({**lot, "qty": qty, "entry": entry, "fees": fees})
        slip = config.slippage_pct / 100
        total_exposure = sum(
            (lot["qty"] * market for group in grouped.values() for lot in group), ZERO
        )
        # Recovery exposure is gross across BOTH active sides, not just the side
        # currently proposing an injection. Runtime RiskEngine also includes any
        # persisted recovery ownership and all pending-order reservations.
        active_recovery_exposure = ZERO
        for side, group in grouped.items():
            if group:
                average = weighted_average(group)
                direction = ONE if side == Side.LONG else -ONE
                adverse = (average - market) * direction / average
                if adverse > 0 and adverse * 100 >= config.recovery_threshold_pct:
                    active_recovery_exposure += sum((lot["qty"] * market for lot in group), ZERO)
        result: list[dict] = []
        for side, group in grouped.items():
            if not group:
                continue
            qty = sum((lot["qty"] for lot in group), ZERO)
            average = weighted_average(group)
            fees = sum((lot["fees"] for lot in group), ZERO)
            direction = ONE if side == Side.LONG else -ONE
            pnl = qty * (market - average) * direction
            adverse_fraction = max(ZERO, (average - market) * direction / average)
            if pnl >= 0 or adverse_fraction * 100 < config.recovery_threshold_pct:
                continue
            retrace = config.recovery_retrace_pct / 100
            quoted_target = market * (ONE + retrace if side == Side.LONG else ONE - retrace)
            target = (
                round_down(quoted_target, instrument.tick_size)
                if side == Side.LONG
                else round_up(quoted_target, instrument.tick_size)
            )
            true_be = break_even(side, qty, average, fees, self.fee_rate, slip)
            block = {
                "side": side.value,
                "qty": str(qty),
                "notional": str(qty * average),
                "average": str(average),
                "unrealized_pnl": str(pnl),
                "market": str(market),
                "break_even": str(true_be),
                "target": str(target),
                "tp": None,
                "required_qty": None,
                "required_usdt": None,
                "new_average": None,
                "safe": False,
                "reason": "RECOVERY NON SICURO",
                "progress": None,
                "fees": str(fees),
                "profit_target": str(config.recovery_profit_target_usdt),
                "distance_to_break_even_pct": str(abs(true_be - market) / market * 100),
                "risk_validation_required": True,
                "lot_ids": [lot.get("order_link_id") for lot in group],
            }
            try:
                plan = InjectionCalculator.for_exit(
                    side,
                    qty,
                    average,
                    market,
                    target,
                    instrument,
                    fees,
                    self.fee_rate,
                    slip,
                    config.recovery_profit_target_usdt,
                )
                tp = (
                    round_up(plan.break_even, instrument.tick_size)
                    if side == Side.LONG
                    else round_down(plan.break_even, instrument.tick_size)
                )
                projected_recovery = active_recovery_exposure + plan.required_qty * market * (
                    ONE + slip
                )
                projected_total = total_exposure + plan.required_qty * market * (ONE + slip)
                adverse_injection_notional = plan.required_qty * market * (ONE + slip)
                reasons = []
                if instrument.status != "Trading":
                    reasons.append("Instrument non negoziabile")
                if plan.required_qty > min(instrument.max_qty, instrument.max_market_qty):
                    reasons.append("Qty injection supera instrument limits")
                if plan.required_qty * market < instrument.min_notional:
                    reasons.append("Injection inferiore a minNotional")
                if adverse_injection_notional > config.max_injection_usdt:
                    reasons.append("Max Injection superata")
                if projected_recovery > config.max_recovery_exposure_usdt:
                    reasons.append("Max Recovery Exposure superata")
                if projected_total > config.max_exposure_usdt:
                    reasons.append("Max Total Exposure superata")
                if (
                    tp <= 0
                    or (side == Side.LONG and tp > target)
                    or (side == Side.SHORT and tp < target)
                ):
                    reasons.append("TP netto non raggiungibile al retrace modellato")
                block.update(
                    required_qty=str(plan.required_qty),
                    required_usdt=str(plan.required_usdt),
                    new_average=str(plan.new_average),
                    tp=str(tp),
                    estimated_fees=str(plan.estimated_fees),
                    estimated_exit_fees=str(
                        (qty + plan.required_qty)
                        * plan.break_even
                        * (ONE - slip if side == Side.LONG else ONE + slip)
                        * self.fee_rate
                    ),
                    slippage_estimate_usdt=str(
                        plan.required_qty * market * slip
                        + (qty + plan.required_qty) * plan.break_even * slip
                    ),
                    injection_budget_utilization_pct=str(
                        adverse_injection_notional / config.max_injection_usdt * 100
                    ),
                    effective_price=str(plan.effective_price),
                    safe=not reasons,
                    reason="RECOVERY NON SICURO: " + "; ".join(reasons)
                    if reasons
                    else "Calcolo fattibile; Risk Engine obbligatorio prima dell'ordine",
                )
            except (RecoveryError, ValidationError) as exc:
                block["reason"] = f"RECOVERY NON SICURO: {exc}"
            result.append(block)
        return result
