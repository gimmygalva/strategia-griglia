"""Choose a tick-valid exit only after computing the required economic target."""

from dataclasses import dataclass
from decimal import Decimal

from .grid import decimal_value, round_down, round_up
from .models import Side


@dataclass(frozen=True)
class RecoveryTarget:
    price: Decimal
    mathematical: Decimal
    budget: Decimal
    source: str


def select_recovery_tp(
    side: Side,
    mathematical_target: Decimal,
    tick: Decimal,
    levels: dict,
    retrace_limit: Decimal,
) -> tuple[Decimal, str]:
    """Use a confident barrier within the modeled retrace, without lowering net profit.

    LONG exits one tick before resistance; SHORT one tick before support. The
    minimum confidence is an explicit confluence score of 50/100, not probability.
    Missing observations preserve the mathematical target.
    """
    side = Side(side)
    target = decimal_value(mathematical_target)
    tick = decimal_value(tick)
    limit = decimal_value(retrace_limit)
    target = round_up(target, tick) if side == Side.LONG else round_down(target, tick)
    candidates: list[tuple[Decimal, str]] = []
    for name in ("R1", "R2") if side == Side.LONG else ("S1", "S2"):
        if levels.get(name) is None or levels.get(f"{name}_confidence") is None:
            continue
        confidence = decimal_value(levels[f"{name}_confidence"])
        level = decimal_value(levels[name])
        if not Decimal(50) <= confidence <= Decimal(100) or level <= 0:
            continue
        quote = (
            round_down(level - tick, tick) if side == Side.LONG else round_up(level + tick, tick)
        )
        if quote > 0 and (
            (side == Side.LONG and target <= quote <= limit)
            or (side == Side.SHORT and limit <= quote <= target)
        ):
            candidates.append((quote, name))
    if not candidates:
        return target, "Mathematical net target"
    chosen = min(candidates) if side == Side.LONG else max(candidates)
    return chosen[0], f"Mathematical net target + {chosen[1]} confluence"
