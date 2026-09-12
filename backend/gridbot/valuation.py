"""Verified prices, UTC valuation baselines and event-derived portfolio."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal

from .errors import RiskError, ValidationError

D = Decimal


class ValuationMixin:
    async def _fetch_prices(self) -> None:
        result = await self.adapter.public_get(
            "/v5/market/tickers", {"category": "linear", "symbol": self.config.symbol}
        )
        rows = result.get("list", [])
        if len(rows) != 1 or rows[0].get("symbol") != self.config.symbol:
            raise ValidationError("Ticker Bybit non coerente")
        try:
            last = D(rows[0]["lastPrice"])
            mark = D(rows[0]["markPrice"])
            if not all(v.is_finite() and v > 0 for v in [last, mark]):
                raise ValueError("Invalid quotes")
        except (KeyError, ValueError, ArithmeticError) as exc:
            raise ValidationError("Ticker/Mark Bybit non valido") from exc
        self.price, self.mark_price = last, mark
        self.last_mark = time.monotonic()

    async def _daily_baseline(
        self, executions: list[dict] | None = None, orders: list[dict] | None = None
    ) -> dict:
        from .pnl import midnight_unrealized

        now = datetime.fromtimestamp(self.exchange_time_ms() / 1000, timezone.utc)
        day = now.strftime("%Y-%m-%d")
        existing = await self.store.get("pnl_snapshots", f"baseline-{day}")
        if existing and existing.get("source") in {
            "UTC midnight mark candle",
            "No bot position at UTC midnight",
        }:
            return existing
        trades = executions if executions is not None else await self.store.executions()
        orders = orders if orders is not None else await self.store.orders()
        midnight = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        if any(int(r["time_ms"]) < midnight for r in trades):
            if not self.adapter:
                raise RiskError(
                    "Baseline giornaliera non verificabile: connessione Bybit richiesta"
                )
            mark = await self.adapter.midnight_mark(self.config.symbol, midnight)
            unreal = midnight_unrealized(trades, orders, mark, midnight)
            baseline = {
                "unrealized": str(unreal),
                "mark_price": str(mark),
                "source": "UTC midnight mark candle",
            }
        else:
            baseline = {"unrealized": "0", "source": "No bot position at UTC midnight"}
        await self.store.put("pnl_snapshots", f"baseline-{day}", baseline)
        return baseline

    def _analyze_sr(self) -> None:
        from .indicators import SupportResistanceEngine

        if self.candles and self.price is not None:
            self.sr = SupportResistanceEngine().analyze(self.candles, self.price)

    async def portfolio(self, lots: list[dict] | None = None) -> dict[str, str | None]:
        from .pnl import calculate_portfolio

        empty = {
            k: None
            for k in [
                "equity",
                "realized",
                "unrealized",
                "fees",
                "funding",
                "net",
                "today",
                "grid",
                "recovery",
                "long",
                "short",
            ]
        }
        if not self.connected or self.price is None or not self.account:
            return empty
        lots = lots if lots is not None else await self.store.lots()
        executions = await self.store.executions()
        funding_events = await self.store.funding_events()
        orders = await self.store.orders()
        memberships = await self.store.records("recovery_blocks", 100000)
        output = calculate_portfolio(
            executions,
            lots,
            funding_events,
            orders,
            memberships,
            self.mark_price if self.mark_price is not None else self.price,
        )
        baseline = await self._daily_baseline(executions, orders)
        day = datetime.fromtimestamp(self.exchange_time_ms() / 1000, timezone.utc).strftime(
            "%Y-%m-%d"
        )
        day_real = sum(
            (
                D(r["realized_pnl"]) - D(r["fee"])
                for r in executions
                if datetime.fromtimestamp(int(r["time_ms"]) / 1000, timezone.utc).strftime(
                    "%Y-%m-%d"
                )
                == day
            ),
            D(0),
        )
        day_real += sum(
            (
                D(r["amount"])
                for r in funding_events
                if datetime.fromtimestamp(int(r["time_ms"]) / 1000, timezone.utc).strftime(
                    "%Y-%m-%d"
                )
                == day
            ),
            D(0),
        )
        output.update(
            equity=self.account.equity,
            today=day_real + output["unrealized"] - D(baseline["unrealized"]),
        )
        return {k: str(v) for k, v in output.items()}
