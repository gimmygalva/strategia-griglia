"""Exchange stream callbacks; all strategy transitions use the runtime actor."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

from .errors import RiskError, UncertainOrderError
from .models import Side
from .orders import client_id

D = Decimal


class RealtimeMixin:
    async def on_status(self, source: str, connected: bool) -> None:
        if source in {"public", "market"}:
            self.public_connected = connected
            if connected:
                self.last_public = time.monotonic()
        elif source == "private":
            self.private_connected = connected
            if connected:
                self.last_private = time.monotonic()
        if not connected and self.connected and not self.shutting_down:
            await self.fail_safe(RiskError(f"WebSocket {source} scollegato"))

    async def on_event(self, event: dict) -> None:
        async with self.lock:
            try:
                topic = event.get("topic", "")
                data = event.get("data", [])
                if topic.startswith("tickers."):
                    item = data[0] if isinstance(data, list) and data else data
                    market_ts = int(event.get("ts") or time.time() * 1000)
                    if (
                        self.last_market_timestamp is not None
                        and market_ts <= self.last_market_timestamp
                    ):
                        return
                    if item.get("markPrice"):
                        mark = D(item["markPrice"])
                        if not mark.is_finite() or mark <= 0:
                            raise RiskError("Mark realtime non valido")
                        self.mark_price = mark
                        self.last_mark = time.monotonic()
                    if item.get("lastPrice"):
                        quote = D(item["lastPrice"])
                        if not quote.is_finite() or quote <= 0:
                            raise RiskError("Prezzo realtime non valido")
                        self.last_market_timestamp = market_ts
                        self.price = quote
                        self.last_public = time.monotonic()
                        if self.status == "RUNNING" and self.reconciled:
                            previous_center = self.grid.center
                            touches = self.grid.on_price(
                                self.price, int(event.get("ts") or time.time() * 1000)
                            )
                            await self.store.save_grid(self.grid.snapshot(), self.session_id)
                            if previous_center != self.grid.center:
                                await self.notify(
                                    "grid_shifted", "Grid spostata", {"center": self.grid.center}
                                )
                            for touch in touches:
                                key = client_id(
                                    self.session_id, str(touch.index), str(touch.sequence)
                                )
                                await self.store.save_grid(
                                    self.grid.snapshot(),
                                    self.session_id,
                                    {
                                        "key": key,
                                        "event": "grid_touch",
                                        "title": "Livello grid attraversato",
                                        "details": touch.model_dump(mode="json"),
                                    },
                                )
                                await self._pair(str(touch.index), touch.sequence)
                            await self.manager.ensure_protection(self.active_recovery)
                            await self._auto_recovery()
                elif topic.startswith("execution"):
                    for item in data:
                        if item.get("execType", "Trade") == "Funding":
                            raise UncertainOrderError(
                                "Funding ricevuto: riconciliare transaction ledger prima di nuovi ordini"
                            )
                        await self.manager.execution_event(item)
                    self.last_private = time.monotonic()
                    if self.reconciled:
                        if self.active_recovery:
                            await self._recovery_protection()
                        await self.manager.ensure_protection(self.active_recovery)
                elif topic.startswith("order"):
                    for item in data:
                        await self.manager.order_event(item)
                    if self.manager.uncertain:
                        raise UncertainOrderError(
                            "Conferma ordine prima del ledger execution: riconciliazione richiesta"
                        )
                    self.last_private = time.monotonic()
                elif topic.startswith("position"):
                    for item in data:
                        if item.get("symbol") == self.config.symbol:
                            idx = int(item["positionIdx"])
                            size = D(item.get("size", "0"))
                            if idx not in {1, 2} or not size.is_finite() or size < 0:
                                raise RiskError("Aggiornamento posizione Hedge Mode non valido")
                            expected_side = "Buy" if idx == 1 else "Sell"
                            if size > 0 and item.get("side") != expected_side:
                                raise RiskError("Aggiornamento posizione side incoerente")
                            local = sum(
                                (
                                    D(r["qty"])
                                    for r in await self.store.lots()
                                    if Side(r["side"]).position_idx == idx
                                ),
                                D(0),
                            )
                            if size != local:
                                raise UncertainOrderError(
                                    "Posizione ed execution ledger divergono: riconciliazione necessaria"
                                )
                            self.exchange_positions = [
                                r
                                for r in self.exchange_positions
                                if int(r.get("positionIdx", 0)) != int(item["positionIdx"])
                            ] + [item]
                    self.last_private = time.monotonic()
                elif topic.startswith("wallet"):
                    self.last_private = time.monotonic()
                    # REST wallet refresh avoids interpreting sparse coin delta as full equity.
                    self.account = await self.adapter.account()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.fail_safe(exc)
