import asyncio
import hashlib
from decimal import Decimal
from typing import Awaitable, Callable

from .errors import (
    BotError,
    BybitAPIError,
    DatabaseError,
    OrderNotSentError,
    RiskError,
    UncertainOrderError,
)
from .models import Instrument, OrderIntent, RiskContext, Side, StrategyConfig
from .persistence import Store
from .state_machine import exchange_state

D = Decimal
TERMINAL = {"FILLED", "CLOSED", "CANCELED", "REJECTED", "TP_PENDING", "TP_PARTIALLY_FILLED"}


def client_id(*parts: str) -> str:
    return "ghb-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:30]


class OrderManager:
    def __init__(
        self,
        adapter,
        store: Store,
        risk,
        config: StrategyConfig,
        instrument: Instrument,
        context: Callable[[OrderIntent], Awaitable[RiskContext]],
        notify: Callable[[str, str, dict], Awaitable[None]],
        pre_send: Callable[[OrderIntent], None] | None = None,
    ):
        self.adapter, self.store, self.risk = adapter, store, risk
        self.config, self.instrument, self.context, self.notify = (
            config,
            instrument,
            context,
            notify,
        )
        self.lock = asyncio.Lock()
        self.uncertain = False
        self.pre_send = pre_send
        if pre_send is not None and hasattr(adapter, "set_order_guard"):
            adapter.set_order_guard(pre_send)

    async def submit(self, intent: OrderIntent) -> dict:
        async with self.lock:
            existing = await self.store.get_order(intent.order_link_id)
            if existing:
                if (
                    OrderIntent.model_validate(
                        {k: v for k, v in existing.items() if k in OrderIntent.model_fields}
                    )
                    != intent
                ):
                    raise RiskError("OrderLinkId già utilizzato con dati diversi")
                # A committed intent is never sent twice, including crash-before-send.
                return existing
            ctx = await self.context(intent)
            self.risk.validate_order(intent, ctx, self.config, self.instrument)
            row, claimed = await self.store.claim_intent(intent)
            if not claimed:
                return row
            try:
                if self.pre_send:
                    try:
                        self.pre_send(intent)
                    except RiskError as exc:
                        raise OrderNotSentError("Ordine bloccato prima dell'invio") from exc
                result = await self.adapter.create_order(intent)
            except OrderNotSentError as exc:
                await self.store.update_order(intent.order_link_id, "REJECTED", error=exc.code)
                await self.notify(
                    "order_not_sent",
                    "Ordine bloccato prima dell'invio",
                    {"order_link_id": intent.order_link_id, "code": exc.code},
                )
                raise
            except BybitAPIError as exc:
                # Only deterministic validation/business rejections are final. Rate-limit,
                # transport or generic API server failures leave order status uncertain.
                definitive = exc.ret_code in {
                    10001,
                    10003,
                    10004,
                    10005,
                    10007,
                    110004,
                    110006,
                    110007,
                    110012,
                    110013,
                    110017,
                    110020,
                    110032,
                    110094,
                }
                await self.store.update_order(
                    intent.order_link_id, "REJECTED" if definitive else None, error=exc.code
                )
                if definitive:
                    await self.notify(
                        "order_rejected",
                        "Ordine rifiutato",
                        {"order_link_id": intent.order_link_id, "code": exc.code},
                    )
                    raise
                self.uncertain = True
                raise UncertainOrderError(
                    "Stato ordine incerto: riconciliazione obbligatoria"
                ) from exc
            except BotError as exc:
                self.uncertain = True
                await self.store.update_order(intent.order_link_id, error=exc.code)
                raise UncertainOrderError(
                    "Risposta ordine non verificabile: nessun reinvio automatico"
                ) from exc
            except Exception as exc:
                self.uncertain = True
                raise UncertainOrderError("Errore invio ordine: stato incerto") from exc
            if not result.get("orderId"):
                self.uncertain = True
                raise UncertainOrderError("Conferma exchange senza Order ID")
            await self.store.update_order(intent.order_link_id, exchange_id=result["orderId"])
            await self.notify(
                "order_ack",
                "Ordine ricevuto da Bybit",
                {
                    "order_link_id": intent.order_link_id,
                    "order_id": result["orderId"],
                    "side": intent.side.value,
                    "qty": str(intent.qty),
                    "purpose": intent.purpose,
                },
            )
            return await self.store.get_order(intent.order_link_id)

    async def order_event(self, item: dict):
        link = item.get("orderLinkId")
        existing = await self.store.get_order(link) if link else None
        if not existing and item.get("orderId"):
            existing = next(
                (r for r in await self.store.orders() if r["order_id"] == item["orderId"]), None
            )
        if not existing:
            if item.get("symbol") == self.config.symbol:
                self.uncertain = True
                raise RiskError(
                    "Ordine esterno sul simbolo: riconciliazione e conto dedicato richiesti"
                )
            return
        status = exchange_state(item["orderStatus"])
        reported_qty = D(item.get("cumExecQty", "0"))
        if reported_qty != D(existing["executed_qty"]) or (
            status == "FILLED" and D(existing["executed_qty"]) < D(existing["qty"])
        ):
            self.uncertain = True
        await self.store.update_order(existing["order_link_id"], status, item.get("orderId"))
        if status == "REJECTED":
            await self.notify(
                "order_rejected",
                "Ordine rifiutato da Bybit",
                {"order_id": item.get("orderId"), "reason": item.get("rejectReason", "Unknown")},
            )
            raise RiskError("Ordine rifiutato da Bybit; strategia sospesa")

    async def execution_event(self, item: dict) -> bool:
        if item.get("execType", "Trade") != "Trade":
            return False
        known = next(
            (
                r
                for r in await self.store.orders()
                if r["order_link_id"] == item.get("orderLinkId")
                or (r["order_id"] and r["order_id"] == item.get("orderId"))
            ),
            None,
        )
        if not known and item.get("symbol") == self.config.symbol:
            self.uncertain = True
            raise RiskError("Execution esterna sul simbolo: trading bloccato")
        try:
            applied = await self.store.apply_execution(item)
        except Exception as exc:
            self.uncertain = True
            if isinstance(exc, DatabaseError):
                raise
            raise DatabaseError("Impossibile applicare execution in modo transazionale") from exc
        if not applied:
            return False
        row = await self.store.get_order(item.get("orderLinkId", ""))
        if not row:
            row = next(
                (r for r in await self.store.orders() if r["order_id"] == item.get("orderId")), None
            )
        await self.notify(
            "execution",
            "Chiusura eseguita" if row["reduce_only"] else f"{row['side'].title()} eseguito",
            {
                "order_id": item["orderId"],
                "exec_id": item["execId"],
                "price": item["execPrice"],
                "qty": item["execQty"],
                "fees": item.get("execFee", "0"),
                "side": row["side"],
                "purpose": row["purpose"],
            },
        )
        return True

    async def ensure_protection(self, recovery_sides: set[str] | None = None):
        from .grid import take_profit

        recovery_sides = recovery_sides or set()
        lots = {r["order_link_id"]: r for r in await self.store.lots()}
        orders = await self.store.orders()
        for execution in await self.store.executions():
            parent = next((r for r in orders if r["order_link_id"] == execution["link_id"]), None)
            if (
                not parent
                or parent["reduce_only"]
                or (parent["side"] in recovery_sides and parent["purpose"] != "RECOVERY")
            ):
                continue
            if parent["purpose"] == "RECOVERY" and parent["side"] in recovery_sides:
                block_tps = [
                    r
                    for r in orders
                    if r["purpose"] == "RECOVERY_TP"
                    and r["side"] == parent["side"]
                    and r["state"] not in TERMINAL
                ]
                if block_tps:
                    continue
            lot = lots.get(parent["order_link_id"])
            if not lot:
                continue
            link = client_id("tp", parent["order_link_id"], execution["exec_id"])
            existing = await self.store.get_order(link)
            if existing:
                if existing["state"] in {"CANCELED", "REJECTED"} and D(
                    existing["executed_qty"]
                ) < D(existing["qty"]):
                    raise RiskError(
                        "TP cancellato/rifiutato: protezione da ripristinare dopo review"
                    )
                continue
            # Protect each actual fill tranche; never theoretical requested quantity.
            qty = D(execution["qty"])
            # If another close already reduced this lot, do not create overlapping protection.
            covered = sum(
                (
                    D(r["qty"]) - D(r["executed_qty"])
                    for r in orders
                    if r["reduce_only"]
                    and r.get("parent_link_id") == parent["order_link_id"]
                    and r["state"] not in TERMINAL
                ),
                D(0),
            )
            qty = min(qty, D(lot["qty"]) - covered)
            if qty <= 0:
                continue
            tp = take_profit(
                Side(parent["side"]),
                D(execution["price"]),
                self.config.tp_pct / D(100),
                self.instrument.tick_size,
            )
            intent = OrderIntent(
                environment=self.adapter.environment,
                symbol=parent["symbol"],
                order_link_id=link,
                side=Side(parent["side"]),
                qty=qty,
                price=tp,
                order_type="Limit",
                reduce_only=True,
                purpose="TP",
                pair_id=parent.get("pair_id"),
                parent_link_id=parent["order_link_id"],
                slippage_pct=self.config.slippage_pct,
            )
            await self.submit(intent)
            await self.store.put(
                "take_profits",
                link,
                {
                    "parent": parent["order_link_id"],
                    "qty": str(qty),
                    "price": str(tp),
                    "execution_id": execution["exec_id"],
                },
            )
            if parent["state"] == "FILLED":
                await self.store.update_order(parent["order_link_id"], "TP_PENDING")
            orders = await self.store.orders()

    async def cancel(self, row: dict):
        if row["state"] in TERMINAL:
            return
        await self.store.update_order(row["order_link_id"], "CANCEL_PENDING")
        try:
            await self.adapter.cancel_order(row["symbol"], row["order_id"], row["order_link_id"])
        except Exception as exc:
            self.uncertain = True
            raise UncertainOrderError(
                "Cancellazione non confermata: riconciliazione richiesta"
            ) from exc
        # Cancel acknowledgement alone is insufficient. Poll authoritative order state.
        for attempt in range(6):
            item = await self.adapter.find_order(row["symbol"], row["order_link_id"])
            if item:
                await self.order_event(item)
                if exchange_state(item["orderStatus"]) in TERMINAL:
                    return
            await asyncio.sleep(0.15 * (attempt + 1))
        self.uncertain = True
        raise UncertainOrderError("Cancellazione accettata ma stato finale non confermato")

    async def pause_entries(self):
        failures = []
        for row in await self.store.orders():
            if not row["reduce_only"] and row["state"] not in TERMINAL:
                try:
                    await self.cancel(row)
                except BotError as exc:
                    failures.append(exc.code)
        if failures:
            raise UncertainOrderError(
                "STOP locale attivo; alcune cancellazioni Bybit non confermate"
            )

    async def cancel_reductions(self, side: Side):
        for row in await self.store.orders():
            if row["reduce_only"] and row["side"] == side.value and row["state"] not in TERMINAL:
                await self.cancel(row)
