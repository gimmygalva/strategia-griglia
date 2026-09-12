import json
import random
from decimal import Decimal as D

import pytest
from gridbot.errors import ValidationError
from gridbot.grid import GridEngine, round_down, round_up, take_profit, weighted_average
from gridbot.models import Side


def grid() -> GridEngine:
    return GridEngine(D("100"), D("0.01"), 3, D("0.1"), D("0.1"), 1000)


def test_absolute_grid_generation():
    engine = grid()
    assert [(level.index, level.price) for level in engine.levels] == [
        (-3, D(97)),
        (-2, D(98)),
        (-1, D(99)),
        (1, D(101)),
        (2, D(102)),
        (3, D(103)),
    ]


@pytest.mark.parametrize("price", ["104.2", "100", "98.7", "120.45", "85.1"])
def test_shift_keeps_exactly_x_absolute_levels_each_side(price):
    engine = grid()
    original = {level.index: level.price for level in engine.levels}
    engine.shift(D(price))
    assert len(engine.levels) == 6
    assert sum(level.price > D(price) for level in engine.levels) == 3
    assert sum(level.price < D(price) for level in engine.levels) == 3
    for level in engine.levels:
        if level.index in original:
            assert level.price == original[level.index]
    snapshot = engine.snapshot()
    assert engine.shift(D(price)) is False
    assert engine.snapshot() == snapshot


def test_rounding_never_puts_above_level_below_current_price():
    engine = GridEngine(D("100.03"), D("0.017"), 3, D("0.1"), D("0.1"), 1000)
    engine.shift(D("101.72"))
    assert sum(level.price > D("101.72") for level in engine.levels) == 3
    assert sum(level.price < D("101.72") for level in engine.levels) == 3


def test_crossing_uses_hysteresis_not_price_equality():
    engine = grid()
    engine.on_price(D(100), 0)
    assert engine.on_price(D("101.01"), 1000) == []
    touches = engine.on_price(D("101.11"), 2000)
    assert [(touch.index, touch.sequence) for touch in touches] == [(1, 1)]


def test_repeated_reverse_touch_survives_dynamic_shift():
    engine = grid()
    engine.on_price(D(100), 0)
    observations = [("101.2", 1000), ("100.8", 2100), ("101.2", 3200)]
    touches = [touch for price, time in observations for touch in engine.on_price(D(price), time)]
    assert [(touch.index, touch.sequence) for touch in touches] == [(1, 1), (1, 2), (1, 3)]


def test_micro_oscillations_do_not_create_pairs():
    engine = grid()
    engine.on_price(D("100.8"), 0)
    for index in range(1, 501):
        price = D("101.02") if index % 2 else D("100.98")
        assert engine.on_price(price, index * 100) == []


def test_debounce_consumes_suppressed_crossing_without_delayed_touch():
    engine = grid()
    engine.on_price(D(100), 0)
    assert len(engine.on_price(D("101.2"), 1000)) == 1
    assert engine.on_price(D("100.8"), 1100) == []
    assert engine.on_price(D("100.7"), 4000) == []
    assert [touch.sequence for touch in engine.on_price(D("101.2"), 5000)] == [2]


def test_jump_touches_previous_active_window_only_in_direction_order():
    engine = grid()
    engine.on_price(D(100), 0)
    assert [touch.index for touch in engine.on_price(D("110.2"), 1000)] == [1, 2, 3]
    assert [touch.index for touch in engine.on_price(D("100.2"), 3000)] == [9, 8, 7]


def test_duplicate_or_out_of_order_market_frame_changes_nothing():
    engine = grid()
    engine.on_price(D(100), 1000)
    snapshot = engine.snapshot()
    assert engine.on_price(D(120), 1000) == []
    assert engine.on_price(D(80), 999) == []
    assert engine.snapshot() == snapshot


def test_snapshot_json_restore_identical_to_uninterrupted_playback():
    uninterrupted = grid()
    for price, time in [("100", 0), ("101.2", 1000), ("100.8", 1100)]:
        uninterrupted.on_price(D(price), time)
    restarted = GridEngine.restore(json.loads(json.dumps(uninterrupted.snapshot())))
    for price, time in [("100.7", 4000), ("101.2", 5000), ("103.5", 7000), ("100.5", 9000)]:
        assert restarted.on_price(D(price), time) == uninterrupted.on_price(D(price), time)
        assert restarted.snapshot() == uninterrupted.snapshot()


def test_fresh_snapshot_restore():
    assert GridEngine.restore(grid().snapshot()).snapshot() == grid().snapshot()


@pytest.mark.parametrize(
    "mutation",
    [
        {"version": 9},
        {"anchor": "NaN"},
        {"armed": {"1": 4}},
        {"sequences": {"1": -1}},
        {"last_timestamp": -1},
        {"last_price": "0"},
    ],
)
def test_corrupt_snapshot_is_rejected(mutation):
    snapshot = grid().snapshot()
    snapshot.update(mutation)
    with pytest.raises(ValidationError):
        GridEngine.restore(snapshot)


def test_nonpositive_shift_fails_without_mutating_window():
    engine = grid()
    original = engine.snapshot()
    with pytest.raises(ValidationError):
        engine.shift(D("2"))
    assert engine.snapshot() == original


@pytest.mark.parametrize(
    "value,step,down,up",
    [
        ("12.347", "0.1", "12.3", "12.4"),
        ("0.0019", "0.001", "0.001", "0.002"),
        ("12.75", "0.25", "12.75", "12.75"),
        ("1.27", "0.25", "1.25", "1.50"),
    ],
)
def test_non_power_of_ten_tick_and_qty_step_rounding(value, step, down, up):
    assert round_down(D(value), D(step)) == D(down)
    assert round_up(D(value), D(step)) == D(up)


@pytest.mark.parametrize("value,step", [(D("NaN"), D(1)), (D(1), D(0)), (1.25, D(".1"))])
def test_invalid_rounding_inputs_fail(value, step):
    with pytest.raises(ValidationError):
        round_down(value, step)


@pytest.mark.parametrize("side,expected", [(Side.LONG, "101.1"), (Side.SHORT, "99.0")])
def test_tp_uses_actual_entry_and_rounds_away(side, expected):
    assert take_profit(side, D("100.05"), D(".01"), D(".1")) == D(expected)


def test_weighted_average_uses_only_executed_qty():
    lots = [{"qty": "4", "entry": "100", "requested_qty": "10"}, {"qty": "2", "entry": "130"}]
    assert weighted_average(lots) == D(110)


def test_weighted_average_no_execution_fails():
    with pytest.raises(ValidationError):
        weighted_average([])


def test_seeded_historical_price_replay_and_repeated_restart_preserve_every_touch():
    source = random.Random(20260912)
    live = GridEngine(D(67000), D(".005"), 20, D(".1"), D(".5"), 3000)
    replay = GridEngine.restore(live.snapshot())
    price = D(67000)
    sequences = {}
    for index in range(600):
        price += D(source.randint(-9500, 9500)) / 10
        time = index * 4000
        actual = live.on_price(price, time)
        assert actual == replay.on_price(price, time)
        assert live.snapshot() == replay.snapshot()
        assert sum(level.price > price for level in live.levels) == 20
        assert sum(level.price < price for level in live.levels) == 20
        for touch in actual:
            assert touch.sequence == sequences.get(touch.index, 0) + 1
            sequences[touch.index] = touch.sequence
        if index % 37 == 0:
            replay = GridEngine.restore(json.loads(json.dumps(replay.snapshot())))
