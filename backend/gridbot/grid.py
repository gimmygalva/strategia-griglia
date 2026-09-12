"""Deterministic absolute-price grid, suitable for live events and historical playback."""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from .errors import ValidationError
from .models import GridLevel, GridTouch, Side


def decimal_value(value: Any, name: str = "value") -> Decimal:
    """Reject NaN and infinity; never introduce a binary float into money arithmetic."""
    if isinstance(value, float):
        raise ValidationError(f"{name}: usare Decimal o stringa, non float")
    try:
        result = Decimal(value)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise ValidationError(f"{name}: valore decimale non valido") from exc
    if not result.is_finite():
        raise ValidationError(f"{name}: valore non finito")
    return result


def round_down(value: Decimal, step: Decimal) -> Decimal:
    value, step = decimal_value(value), decimal_value(step, "step")
    if step <= 0:
        raise ValidationError("Step deve essere positivo")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def round_up(value: Decimal, step: Decimal) -> Decimal:
    value, step = decimal_value(value), decimal_value(step, "step")
    if step <= 0:
        raise ValidationError("Step deve essere positivo")
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def take_profit(side: Side, entry: Decimal, tp_fraction: Decimal, tick_size: Decimal) -> Decimal:
    """Round away from entry so normalization cannot reduce the requested gross TP."""
    side = Side(side)
    entry, tp_fraction = decimal_value(entry), decimal_value(tp_fraction)
    if entry <= 0 or not 0 < tp_fraction < 1:
        raise ValidationError("Entry o take profit non validi")
    raw = entry * (1 + tp_fraction if side == Side.LONG else 1 - tp_fraction)
    result = round_up(raw, tick_size) if side == Side.LONG else round_down(raw, tick_size)
    if result <= 0:
        raise ValidationError("Take profit non positivo dopo normalizzazione")
    return result


def weighted_average(lots: list[dict]) -> Decimal:
    """Average only the supplied executed remaining quantities, never requested quantities."""
    qty = Decimal("0")
    notional = Decimal("0")
    for lot in lots:
        executed = decimal_value(lot["qty"], "executed qty")
        price = decimal_value(lot["entry"], "execution price")
        if executed < 0 or price <= 0:
            raise ValidationError("Lotto eseguito non valido")
        qty += executed
        notional += executed * price
    if qty <= 0:
        raise ValidationError("Nessuna quantità eseguita per prezzo medio")
    return notional / qty


class GridEngine:
    """A fixed lattice whose active 2X-level window follows the observed market.

    A touch requires crossing both hysteresis boundaries. Suppressed crossings consume
    their direction too: debounce must never queue a later fictitious touch. Event time
    is monotonic; old/duplicate price frames are ignored without changing the window.
    """

    def __init__(
        self,
        anchor: Decimal,
        spacing: Decimal,
        levels: int,
        tick_size: Decimal,
        hysteresis: Decimal,
        debounce_ms: int,
    ) -> None:
        self.anchor = decimal_value(anchor, "anchor")
        self.spacing = decimal_value(spacing, "spacing")
        self.tick_size = decimal_value(tick_size, "tick size")
        self.hysteresis = decimal_value(hysteresis, "hysteresis")
        self.level_count = levels
        self.debounce_ms = debounce_ms
        if self.anchor <= 0 or self.spacing <= 0 or self.tick_size <= 0 or self.hysteresis <= 0:
            raise ValidationError("Parametri grid devono essere positivi")
        if isinstance(levels, bool) or not isinstance(levels, int) or not 1 <= levels <= 100:
            raise ValidationError("Numero livelli non valido")
        if isinstance(debounce_ms, bool) or not isinstance(debounce_ms, int) or debounce_ms < 1:
            raise ValidationError("Debounce non valido")
        self.step = self.anchor * self.spacing
        if self.step < self.tick_size or self.hysteresis * 2 >= self.step:
            raise ValidationError("Spaziatura grid insufficiente per tick/hysteresis")
        self.center = 0
        self._last_price: Decimal | None = None
        self._last_timestamp: int | None = None
        self._armed: dict[int, int] = {}
        self._sequences: dict[int, int] = {}
        self._last_touch: dict[int, int] = {}
        _ = self.levels  # Validate positive and distinct grid prices immediately.

    def _level_price(self, index: int) -> Decimal:
        return round_down(self.anchor + index * self.step, self.tick_size)

    @property
    def levels(self) -> list[GridLevel]:
        indices = list(range(self.center - self.level_count, self.center))
        indices += list(range(self.center + 1, self.center + self.level_count + 1))
        result = [GridLevel(index=i, price=self._level_price(i)) for i in indices]
        if any(level.price <= 0 for level in result):
            raise ValidationError("Finestra grid include prezzi non positivi: trading sospeso")
        if len({level.price for level in result}) != 2 * self.level_count:
            raise ValidationError("Normalizzazione tick crea livelli duplicati")
        return result

    def _side(self, price: Decimal, level: Decimal) -> int:
        if price <= level - self.hysteresis:
            return -1
        if price >= level + self.hysteresis:
            return 1
        return 0

    def shift(self, price: Decimal) -> bool:
        price = decimal_value(price, "market price")
        if price <= 0:
            raise ValidationError("Prezzo mercato non positivo")
        # Rounding lattice prices down can put the next lattice price slightly below
        # market. Adjust using actual tick-normalized prices, not unrounded geometry.
        new_center = int(
            ((price - self.anchor) / self.step).to_integral_value(rounding=ROUND_FLOOR)
        )
        while self._level_price(new_center + 1) <= price:
            new_center += 1
        while self._level_price(new_center) > price:
            new_center -= 1
        if new_center == self.center:
            return False
        old_indices = {level.index for level in self.levels}
        old_center = self.center
        self.center = new_center
        try:
            new_levels = self.levels
        except ValidationError:
            self.center = old_center
            raise
        # The current cell's lower boundary remains watched if it was an active
        # level before the shift. Otherwise moving the window would erase the very
        # level just crossed and a subsequent reverse crossing would be missed.
        active_indices = {level.index for level in new_levels} | {self.center}
        self._armed = {
            index: side for index, side in self._armed.items() if index in active_indices
        }
        for level in new_levels:
            if level.index not in old_indices:
                self._armed[level.index] = self._side(price, level.price)
        return True

    def on_price(self, price: Decimal, timestamp_ms: int) -> list[GridTouch]:
        price = decimal_value(price, "market price")
        if (
            price <= 0
            or isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, int)
            or timestamp_ms < 0
        ):
            raise ValidationError("Evento prezzo non valido")
        if self._last_timestamp is not None and timestamp_ms <= self._last_timestamp:
            return []
        touches: list[GridTouch] = []
        active = self.levels
        if self.center in self._armed:
            active.append(GridLevel(index=self.center, price=self._level_price(self.center)))
            active.sort(key=lambda level: level.price)
        if self._last_price is None:
            self._armed = {level.index: self._side(price, level.price) for level in active}
        else:
            if price < self._last_price:
                active.reverse()
            for level in active:
                observed = self._side(price, level.price)
                armed = self._armed.get(level.index, self._side(self._last_price, level.price))
                if observed == 0:
                    continue
                self._armed[level.index] = observed
                if armed == 0 or observed == armed:
                    continue
                last_touch = self._last_touch.get(level.index)
                if last_touch is not None and timestamp_ms - last_touch < self.debounce_ms:
                    continue
                sequence = self._sequences.get(level.index, 0) + 1
                self._sequences[level.index] = sequence
                self._last_touch[level.index] = timestamp_ms
                touches.append(GridTouch(index=level.index, price=level.price, sequence=sequence))
        self.shift(price)
        self._last_price, self._last_timestamp = price, timestamp_ms
        return touches

    def snapshot(self) -> dict:
        return {
            "version": 1,
            "anchor": str(self.anchor),
            "spacing": str(self.spacing),
            "levels": self.level_count,
            "tick_size": str(self.tick_size),
            "hysteresis": str(self.hysteresis),
            "debounce_ms": self.debounce_ms,
            "center": self.center,
            "last_price": str(self._last_price) if self._last_price is not None else None,
            "last_timestamp": self._last_timestamp,
            "armed": {str(k): v for k, v in self._armed.items()},
            "sequences": {str(k): v for k, v in self._sequences.items()},
            "last_touch": {str(k): v for k, v in self._last_touch.items()},
        }

    @classmethod
    def restore(cls, snapshot: dict) -> "GridEngine":
        if snapshot.get("version") != 1:
            raise ValidationError("Versione snapshot grid non supportata")
        try:
            engine = cls(
                Decimal(snapshot["anchor"]),
                Decimal(snapshot["spacing"]),
                snapshot["levels"],
                Decimal(snapshot["tick_size"]),
                Decimal(snapshot["hysteresis"]),
                snapshot["debounce_ms"],
            )
            engine.center = int(snapshot["center"])
            _ = engine.levels
            engine._last_price = (
                decimal_value(snapshot["last_price"])
                if snapshot["last_price"] is not None
                else None
            )
            engine._last_timestamp = snapshot["last_timestamp"]
            engine._armed = {int(k): int(v) for k, v in snapshot["armed"].items()}
            engine._sequences = {int(k): int(v) for k, v in snapshot["sequences"].items()}
            engine._last_touch = {int(k): int(v) for k, v in snapshot["last_touch"].items()}
            if any(v not in (-1, 0, 1) for v in engine._armed.values()):
                raise ValidationError("Stato hysteresis grid corrotto")
            if any(v < 0 for v in engine._sequences.values()) or any(
                v < 0 for v in engine._last_touch.values()
            ):
                raise ValidationError("Contatore grid corrotto")
            if engine._last_timestamp is not None and (
                not isinstance(engine._last_timestamp, int) or engine._last_timestamp < 0
            ):
                raise ValidationError("Timestamp grid corrotto")
            if engine._last_price is not None and engine._last_price <= 0:
                raise ValidationError("Prezzo snapshot grid corrotto")
            return engine
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ValidationError("Snapshot grid non valido") from exc
