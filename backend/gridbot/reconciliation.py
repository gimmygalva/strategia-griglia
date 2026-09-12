from decimal import Decimal

from .errors import RiskError, UncertainOrderError
from .models import Side
from .orders import TERMINAL

D = Decimal


class ReconciliationService:
    def __init__(self, adapter, store, manager, symbol):
        self.adapter, self.store, self.manager, self.symbol = adapter, store, manager, symbol

    async def run(self) -> tuple[list[dict], list[dict]]:
        # Fetch trade ledger before comparing aggregate positions; window is bounded to
        # Bybit retention. A historical gap can never justify a guessed local fill.
        all_exec = await self.store.executions()
        orders = await self.store.orders()
        start = min((int(r["time_ms"]) for r in all_exec), default=None)
        if orders:
            from datetime import datetime

            earliest = min(
                int(datetime.fromisoformat(r["created_at"]).timestamp() * 1000) for r in orders
            )
            start = min(start, earliest) if start is not None else earliest
        trades = await self.adapter.executions(self.symbol, start)
        if orders:
            for item in await self.adapter.transactions(self.symbol, start):
                await self.store.apply_funding_transaction(item)
        known_links = {r["order_link_id"] for r in orders}
        known_ids = {r["order_id"] for r in orders if r["order_id"]}
        for item in sorted(trades, key=lambda x: (int(x["execTime"]), str(x["execId"]))):
            if item.get("orderLinkId") in known_links or item.get("orderId") in known_ids:
                await self.manager.execution_event(item)
        pending = []
        for row in await self.store.orders():
            # Even terminal order reports can precede execution events; query until
            # actual fills agree with cumulative exchange execution quantity.
            item = await self.adapter.find_order(self.symbol, row["order_link_id"])
            if item:
                await self.manager.order_event(item)
                current = await self.store.get_order(row["order_link_id"])
                cumulative = D(item.get("cumExecQty", "0"))
                if cumulative != D(current["executed_qty"]):
                    pending.append(row["order_link_id"])
            elif row["state"] not in TERMINAL:
                pending.append(row["order_link_id"])
        opened = await self.adapter.open_orders(self.symbol)
        known = {r["order_link_id"] for r in await self.store.orders()}
        if any(r.get("orderLinkId") not in known for r in opened):
            raise RiskError("Ordini esterni sul simbolo: usare account/subaccount dedicato")
        positions = await self.adapter.positions(self.symbol)
        lots = await self.store.lots()
        for side in Side:
            local = sum((D(r["qty"]) for r in lots if r["side"] == side.value), D(0))
            exchange = sum(
                (
                    D(r.get("size", "0"))
                    for r in positions
                    if int(r.get("positionIdx", 0)) == side.position_idx
                ),
                D(0),
            )
            if local != exchange:
                raise RiskError(
                    f"{side.value}: posizioni Bybit e database divergono; trading sospeso"
                )
        if pending:
            raise UncertainOrderError("Ordini/fill non riconciliati: nessun reinvio automatico")
        self.manager.uncertain = False
        await self.store.put("positions", "authoritative", {"positions": positions})
        return opened, positions
