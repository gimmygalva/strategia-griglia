from decimal import Decimal as D

import pytest
from gridbot.errors import ValidationError
from gridbot.models import Side
from gridbot.recovery_targets import select_recovery_tp


@pytest.mark.parametrize(
    "side,target,levels,limit,expected",
    [
        (Side.LONG, "100.01", {}, "105", "100.1"),
        (Side.SHORT, "99.99", {}, "95", "99.9"),
        (Side.LONG, "100", {"R1": "102", "R1_confidence": "65"}, "105", "101.9"),
        (Side.SHORT, "100", {"S1": "98", "S1_confidence": "65"}, "95", "98.1"),
        (Side.LONG, "100", {"R1": "99", "R1_confidence": "65"}, "105", "100"),
        (Side.SHORT, "100", {"S1": "101", "S1_confidence": "65"}, "95", "100"),
        (Side.LONG, "100", {"R1": "110", "R1_confidence": "65"}, "105", "100"),
        (Side.SHORT, "100", {"S1": "90", "S1_confidence": "65"}, "95", "100"),
        (Side.LONG, "100", {"R1": "102", "R1_confidence": "49"}, "105", "100"),
    ],
)
def test_sr_never_violates_math_net_floor_or_retrace(side, target, levels, limit, expected):
    quote, reason = select_recovery_tp(side, D(target), D(".1"), levels, D(limit))
    assert quote == D(expected)
    assert quote % D(".1") == 0
    assert (quote >= D(target)) if side == Side.LONG else (quote <= D(target))
    assert reason.startswith("Mathematical net target")


def test_nearest_valid_confident_resistance_is_deterministic():
    levels = {"R1": "102", "R2": "104", "R1_confidence": "65", "R2_confidence": "85"}
    assert select_recovery_tp(Side.LONG, D(100), D(".1"), levels, D(105))[0] == D("101.9")


def test_nonfinite_sr_cannot_generate_order_price():
    with pytest.raises(ValidationError):
        select_recovery_tp(Side.LONG, D(100), D(".1"), {"R1": "NaN", "R1_confidence": "65"}, D(105))
