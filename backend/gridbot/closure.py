"""Preflight and confirmed reductions; no implicit position liquidation."""

from __future__ import annotations

import time
from decimal import Decimal

from .errors import RiskError
from .models import Environment, OrderIntent, Side
from .orders import client_id

D = Decimal


class ClosureMixin:
    def _close_chunks(self, qty: Decimal, market: bool) -> list[Decimal]:
        from .grid import round_down

        cap = (
            min(self.instrument.max_qty, self.instrument.max_market_qty)
            if market
            else self.instrument.max_qty
        )
        cap = round_down(cap, self.instrument.qty_step)
        minimum = self.instrument.min_qty
        chunks = []
        while qty > 0:
            chunk = min(qty, cap)
            residue = qty - chunk
            if 0 < residue < minimum:
                chunk = round_down(qty - minimum, self.instrument.qty_step)
            if chunk < minimum:
                raise RiskError(
                    "Quantità residua non chiudibile secondo instrument rules; TP mantenuti"
                )
            chunks.append(chunk)
            qty -= chunk
        return chunks

    async def _preflight_reductions(
        self, side: Side, qty: Decimal, price: Decimal | None = None, purpose: str = "CLOSE"
    ) -> None:
        for index, chunk in enumerate(self._close_chunks(qty, price is None)):
            intent = OrderIntent(
                environment=self.environment,
                symbol=self.config.symbol,
                order_link_id=client_id("preflight", side.value, str(index)),
                side=side,
                qty=chunk,
                price=price,
                order_type="Market" if price is None else "Limit",
                reduce_only=True,
                purpose=purpose,
                slippage_pct=self.config.slippage_pct,
            )
            ctx = await self.risk_context(intent)
            ctx.position_qty = qty
            self.manager.risk.validate_order(intent, ctx, self.config, self.instrument)

    async def close_all(self, confirm: str, ack: bool) -> None:
        if confirm != "CHIUDI TUTTO" or not ack:
            raise RiskError("Doppia conferma CHIUDI TUTTO necessaria")
        self.status = "PAUSED"
        async with self.lock:
            if not self.manager or not self.connected:
                raise RiskError("Connessione Bybit necessaria per chiudere")
            if self.environment == Environment.MAINNET:
                if not self.mainnet_allowed:
                    raise RiskError("Mainnet disabilitata lato backend")
                self.live_confirmed = True
                self.adapter.set_live_authorization(True, True)
            try:
                await self._reconcile()
                for side in Side:
                    total = sum(
                        (D(r["qty"]) for r in await self.store.lots() if r["side"] == side.value),
                        D(0),
                    )
                    if total:
                        await self._preflight_reductions(side, total)
                await self.manager.pause_entries()
                for side in Side:
                    await self.manager.cancel_reductions(side)
                await self._reconcile()
                for side in Side:
                    qty = sum(
                        (D(r["qty"]) for r in await self.store.lots() if r["side"] == side.value),
                        D(0),
                    )
                    if qty:
                        operation = str(time.time_ns())
                        for index, chunk in enumerate(self._close_chunks(qty, True)):
                            intent = OrderIntent(
                                environment=self.environment,
                                symbol=self.config.symbol,
                                order_link_id=client_id("close", side.value, operation, str(index)),
                                side=side,
                                qty=chunk,
                                reduce_only=True,
                                purpose="CLOSE",
                                slippage_pct=self.config.slippage_pct,
                            )
                            await self.manager.submit(intent)
                await self.notify(
                    "close_all", "Chiusura richiesta per tutte le posizioni del bot", {}
                )
            except Exception as exc:
                await self.fail_safe(exc)
                raise
