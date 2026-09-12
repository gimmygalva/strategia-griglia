"""Transparent ATR/EMA/confirmed-pivot support and resistance calculations."""

from decimal import Decimal

from .errors import ValidationError
from .grid import decimal_value

ZERO = Decimal("0")


def normalize_candles(candles: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[int] = set()
    for raw in candles:
        try:
            time = int(raw["time"])
            o, h, low, c, v = (
                decimal_value(raw[key], key) for key in ("open", "high", "low", "close", "volume")
            )
        except (KeyError, ValueError, TypeError, ValidationError) as exc:
            raise ValidationError("Candela OHLCV non valida") from exc
        if (
            time < 0
            or time in seen
            or min(o, h, low, c) <= 0
            or v < 0
            or not low <= min(o, c) <= max(o, c) <= h
        ):
            raise ValidationError("Candela OHLCV incoerente o timestamp duplicato")
        seen.add(time)
        normalized.append({"time": time, "open": o, "high": h, "low": low, "close": c, "volume": v})
    return sorted(normalized, key=lambda candle: candle["time"])


def atr(candles: list[dict], period: int = 14) -> Decimal | None:
    """Wilder ATR using only real normalized closed candles."""
    if period < 1:
        raise ValidationError("ATR period non valido")
    if len(candles) < period + 1:
        return None
    ranges = [
        max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous["close"]),
            abs(candle["low"] - previous["close"]),
        )
        for previous, candle in zip(candles, candles[1:], strict=False)
    ]
    value = sum(ranges[:period], ZERO) / period
    for true_range in ranges[period:]:
        value = (value * (period - 1) + true_range) / period
    return value


def ema(closes: list[Decimal], period: int = 20) -> Decimal | None:
    if period < 1:
        raise ValidationError("EMA period non valido")
    if len(closes) < period:
        return None
    value = sum(closes[:period], ZERO) / period
    alpha = Decimal(2) / (period + 1)
    for close in closes[period:]:
        value += alpha * (close - value)
    return value


class SupportResistanceEngine:
    """Cluster confirmed ±2-bar pivots and prior range/EMA confluence.

    Confidence is a deterministic technical confluence score, not a forecast
    probability or a guarantee that support/resistance will hold.
    """

    def analyze(self, candles: list[dict], price: Decimal) -> dict:
        price = decimal_value(price, "price")
        if price <= 0:
            raise ValidationError("Prezzo indicatori non positivo")
        all_candles = normalize_candles(candles)
        # REST klines generally include the current, unclosed bar. Excluding it is
        # deliberately conservative and prevents moving pivots within that bar.
        closed = all_candles[:-1]
        current_atr = atr(closed)
        current_ema = ema([candle["close"] for candle in closed])
        result: dict = {
            "S1": None,
            "S2": None,
            "R1": None,
            "R2": None,
            "confidence": None,
            "atr": str(current_atr) if current_atr is not None else None,
            "ema": str(current_ema) if current_ema is not None else None,
            "closed_candles": len(closed),
            "method": "confirmed-pivot-2 / Wilder ATR14 / EMA20",
        }
        if current_atr is None or not closed:
            return result
        tolerance = max(current_atr * Decimal("0.35"), price * Decimal("0.0001"))
        candidates: list[tuple[Decimal, int, Decimal, str]] = []
        for index in range(2, len(closed) - 2):
            candle = closed[index]
            neighbors = closed[index - 2 : index] + closed[index + 1 : index + 3]
            if all(candle["high"] > other["high"] for other in neighbors):
                candidates.append((candle["high"], index, candle["volume"], "pivot"))
            if all(candle["low"] < other["low"] for other in neighbors):
                candidates.append((candle["low"], index, candle["volume"], "pivot"))
        recent = closed[-20:]
        offset = len(closed) - len(recent)
        hi = max(range(len(recent)), key=lambda index: recent[index]["high"])
        low = min(range(len(recent)), key=lambda index: recent[index]["low"])
        candidates += [
            (recent[hi]["high"], offset + hi, recent[hi]["volume"], "range"),
            (recent[low]["low"], offset + low, recent[low]["volume"], "range"),
            (closed[-1]["high"], len(closed) - 1, closed[-1]["volume"], "previous"),
            (closed[-1]["low"], len(closed) - 1, closed[-1]["volume"], "previous"),
        ]
        if current_ema is not None:
            candidates.append((current_ema, len(closed) - 1, ZERO, "ema"))
        clusters: list[list[tuple[Decimal, int, Decimal, str]]] = []
        for candidate in sorted(candidates):
            if clusters and candidate[0] - clusters[-1][0][0] <= tolerance:
                clusters[-1].append(candidate)
            else:
                clusters.append([candidate])
        max_volume = max((candle["volume"] for candle in closed), default=ZERO)
        scored: list[tuple[Decimal, Decimal, list[str]]] = []
        for cluster in clusters:
            # Only actual observed level values enter the arithmetic mean.
            level = sum((item[0] for item in cluster), ZERO) / len(cluster)
            sources = sorted({item[3] for item in cluster})
            touches = sum(
                1
                for candle in closed
                if candle["low"] - tolerance <= level <= candle["high"] + tolerance
            )
            recency = Decimal(max(item[1] for item in cluster) + 1) / len(closed)
            volume = max(item[2] for item in cluster) / max_volume if max_volume else ZERO
            score = min(
                Decimal(100),
                Decimal(min(3, len(sources))) * 10
                + recency * 20
                + volume * 20
                + Decimal(min(6, touches)) * 5,
            )
            scored.append((level, score, sources))
        supports = sorted((item for item in scored if item[0] < price), reverse=True)
        resistances = sorted(item for item in scored if item[0] > price)
        selected: list[tuple[Decimal, Decimal, list[str]]] = []
        for names, levels in ((["S1", "S2"], supports), (["R1", "R2"], resistances)):
            for name, (level, score, sources) in zip(names, levels, strict=False):
                result[name] = str(level)
                result[f"{name}_confidence"] = str(score)
                result[f"{name}_sources"] = sources
                selected.append((level, score, sources))
        if selected:
            result["confidence"] = str(sum((item[1] for item in selected), ZERO) / len(selected))
        return result
