from decimal import Decimal as D

import pytest
from gridbot.errors import ValidationError
from gridbot.indicators import SupportResistanceEngine, atr, ema, normalize_candles


def candles(count=41):
    # Deliberately generated OHLCV fixture for algorithm tests, never production data.
    values = []
    for index in range(count):
        close = D(100) + D(index % 10 - 5)
        values.append(
            {
                "time": index * 900,
                "open": str(close),
                "high": str(close + 2),
                "low": str(close - 2),
                "close": str(close),
                "volume": str(10 + index % 3),
            }
        )
    return values


def test_empty_market_history_returns_unknown_not_fabricated_levels():
    result = SupportResistanceEngine().analyze([], D(100))
    assert all(result[key] is None for key in ("S1", "S2", "R1", "R2", "confidence", "atr", "ema"))


def test_insufficient_history_has_no_atr_or_fake_confidence():
    result = SupportResistanceEngine().analyze(candles(10), D(100))
    assert result["atr"] is None and result["confidence"] is None


def test_atr_independent_true_range_average_and_wilder_update():
    fixture = normalize_candles(
        [
            {"time": 0, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"},
            {"time": 1, "open": "103", "high": "105", "low": "102", "close": "104", "volume": "1"},
            {"time": 2, "open": "104", "high": "106", "low": "103", "close": "105", "volume": "1"},
            {"time": 3, "open": "100", "high": "102", "low": "99", "close": "101", "volume": "1"},
        ]
    )
    # True ranges 5,3,6; ATR2 initial4, next(4+6)/2=5.
    assert atr(fixture, 2) == D(5)


def test_ema_uses_sma_seed_independent_result():
    assert ema([D(1), D(2), D(3), D(7)], 3) == D("4.5")


def test_sr_levels_strictly_on_correct_side_and_scores_bounded():
    result = SupportResistanceEngine().analyze(candles(), D(100))
    assert D(result["S1"]) < 100 < D(result["R1"])
    if result["S2"] is not None:
        assert D(result["S2"]) < D(result["S1"])
    if result["R2"] is not None:
        assert D(result["R1"]) < D(result["R2"])
    assert 0 <= D(result["confidence"]) <= 100
    assert result["closed_candles"] == 40


def test_current_unclosed_candle_never_changes_confirmed_sr():
    fixture = candles()
    baseline = SupportResistanceEngine().analyze(fixture, D(100))
    fixture[-1] = {
        **fixture[-1],
        "open": "1000",
        "high": "2000",
        "low": "1",
        "close": "1000",
        "volume": "999999",
    }
    assert SupportResistanceEngine().analyze(fixture, D(100)) == baseline


def test_rest_descending_candles_and_ascending_have_equal_output():
    fixture = candles()
    assert SupportResistanceEngine().analyze(fixture, D(100)) == SupportResistanceEngine().analyze(
        list(reversed(fixture)), D(100)
    )


@pytest.mark.parametrize(
    "changes", [{"high": "1"}, {"low": "200"}, {"volume": "-1"}, {"close": "NaN"}, {"close": 100.0}]
)
def test_bad_ohlcv_blocks_indicator_computation(changes):
    fixture = candles()
    fixture[2].update(changes)
    with pytest.raises(ValidationError):
        SupportResistanceEngine().analyze(fixture, D(100))


def test_duplicate_candle_timestamp_is_rejected():
    fixture = candles()
    fixture[2]["time"] = fixture[1]["time"]
    with pytest.raises(ValidationError):
        SupportResistanceEngine().analyze(fixture, D(100))
