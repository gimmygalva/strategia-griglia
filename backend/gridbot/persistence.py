import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .errors import DatabaseError, ValidationError
from .models import OrderIntent, Side
from .schema import RECORDS, Execution, FundingEvent, Lot, Order
from .state_machine import transition

D = Decimal


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def order_dict(row: Order) -> dict:
    return {
        "order_link_id": row.link_id,
        "order_id": row.exchange_id,
        "state": row.state,
        **row.intent,
        "executed_qty": row.executed_qty,
        "executed_notional": row.executed_notional,
        "fees": row.fees,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "error": row.error,
    }


class Store:
    """One SQLite file per environment, durable intent before network mutation."""

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.engine = create_async_engine("sqlite+aiosqlite:///" + str(self.path))

        @event.listens_for(self.engine.sync_engine, "connect")
        def configure(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        def migrate():
            cfg = Config()
            cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
            cfg.set_main_option("sqlalchemy.url", "sqlite:///" + str(self.path))
            command.upgrade(cfg, "head")
            self.path.chmod(0o600)

        try:
            await asyncio.to_thread(migrate)
        except Exception as exc:
            raise DatabaseError("Migrazione database fallita") from exc

    async def close(self):
        await self.engine.dispose()

    async def claim_intent(self, intent: OrderIntent) -> tuple[dict, bool]:
        async with self.lock, self.sessions.begin() as session:
            row = await session.get(Order, intent.order_link_id)
            if row:
                if row.intent != intent.model_dump(mode="json"):
                    raise ValidationError("OrderLinkId riutilizzato con parametri differenti")
                return order_dict(row), False
            now = utcnow()
            row = Order(
                link_id=intent.order_link_id,
                state="PENDING_CREATE",
                intent=intent.model_dump(mode="json"),
                executed_qty="0",
                executed_notional="0",
                fees="0",
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return order_dict(row), True

    async def get_order(self, link_id: str) -> dict | None:
        async with self.sessions() as session:
            row = await session.get(Order, link_id)
            return order_dict(row) if row else None

    async def orders(self) -> list[dict]:
        async with self.sessions() as session:
            rows = (await session.scalars(select(Order).order_by(Order.created_at))).all()
            return [order_dict(row) for row in rows]

    async def update_order(
        self,
        link_id: str,
        state: str | None = None,
        exchange_id: str | None = None,
        error: str | None = None,
    ):
        async with self.lock, self.sessions.begin() as session:
            row = await session.get(Order, link_id)
            if not row:
                raise DatabaseError("Ordine locale mancante")
            if exchange_id:
                if row.exchange_id and row.exchange_id != exchange_id:
                    raise DatabaseError("OrderLinkId con exchange ID incoerente")
                row.exchange_id = exchange_id
            if state:
                row.state = transition(row.state, state, stale_ok=True)
            row.updated_at = utcnow()
            row.error = error

    async def apply_execution(self, payload: dict) -> bool:
        """Dedup + order fill + owned lot + close PnL form a single transaction."""
        try:
            exec_id = str(payload["execId"])
            qty, price, fee = (
                D(payload["execQty"]),
                D(payload["execPrice"]),
                D(payload.get("execFee", "0")),
            )
            if (
                not exec_id
                or not payload.get("orderId")
                or not str(payload.get("execTime", "")).isdigit()
            ):
                raise ValueError("Execution senza identificatori")
            if not all(v.is_finite() for v in [qty, price, fee]) or qty <= 0 or price <= 0:
                raise ValueError("Execution quantitativo non valido")
        except (ValueError, KeyError, ArithmeticError) as exc:
            raise DatabaseError("Execution non valida") from exc
        async with self.lock, self.sessions.begin() as session:
            previous = await session.get(Execution, exec_id)
            if previous:
                if (
                    D(previous.qty) != qty
                    or D(previous.price) != price
                    or D(previous.fee) != fee
                    or previous.exchange_id != payload["orderId"]
                ):
                    raise DatabaseError("Execution ID duplicato con dati incoerenti")
                return False
            link = payload.get("orderLinkId")
            row = await session.get(Order, link) if link else None
            if not row and payload.get("orderId"):
                row = await session.scalar(
                    select(Order).where(Order.exchange_id == payload["orderId"])
                )
            if not row:
                # Unrelated manual/account trades are not claimed as bot executions.
                return False
            intent = OrderIntent.model_validate(row.intent)
            if payload.get("symbol") and payload["symbol"] != intent.symbol:
                raise DatabaseError("Execution symbol incoerente")
            if row.exchange_id and row.exchange_id != payload["orderId"]:
                raise DatabaseError("Execution exchange ID incoerente")
            if "positionIdx" in payload and int(payload["positionIdx"]) != intent.side.position_idx:
                raise DatabaseError("Execution Hedge positionIdx incoerente")
            expected_side = (
                intent.side.closing_side if intent.reduce_only else intent.side.opening_side
            )
            if payload.get("side") and payload["side"] != expected_side:
                raise DatabaseError("Execution side incoerente")
            if row.state == "REJECTED":
                raise DatabaseError("Execution contraddice rifiuto definitivo ordine")
            new_qty = D(row.executed_qty) + qty
            if new_qty > intent.qty:
                raise DatabaseError("Execution supera quantità richiesta")
            row.exchange_id = payload.get("orderId") or row.exchange_id
            row.executed_qty = str(new_qty)
            row.executed_notional = str(D(row.executed_notional) + qty * price)
            row.fees = str(D(row.fees) + fee)
            row.state = transition(
                row.state, "FILLED" if new_qty == intent.qty else "PARTIALLY_FILLED", stale_ok=True
            )
            row.updated_at = utcnow()
            realized = D(0)
            allocations = []
            if not intent.reduce_only:
                lot = await session.get(Lot, row.link_id)
                if lot:
                    old_qty = D(lot.remaining_qty)
                    lot.entry = str((D(lot.entry) * old_qty + price * qty) / (old_qty + qty))
                    lot.qty = str(D(lot.qty) + qty)
                    lot.remaining_qty = str(D(lot.remaining_qty) + qty)
                    lot.fees = str(D(lot.fees) + fee)
                else:
                    session.add(
                        Lot(
                            link_id=row.link_id,
                            side=intent.side.value,
                            qty=str(qty),
                            remaining_qty=str(qty),
                            entry=str(price),
                            fees=str(fee),
                            pair_id=intent.pair_id,
                            purpose=intent.purpose,
                        )
                    )
            else:
                if intent.parent_link_id:
                    lots = [await session.get(Lot, intent.parent_link_id)]
                else:
                    lots = (
                        await session.scalars(select(Lot).where(Lot.side == intent.side.value))
                    ).all()
                remaining = qty
                for lot in lots:
                    if not lot or lot.side != intent.side.value:
                        raise DatabaseError("TP non associato alla posizione corretta")
                    if D(lot.remaining_qty) == 0:
                        # Earlier partial reductions can exhaust a lot. Its historical
                        # row remains for audit, but cannot receive another allocation.
                        continue
                    allocation = min(remaining, D(lot.remaining_qty))
                    part_pnl = (
                        allocation
                        * (price - D(lot.entry))
                        * (1 if intent.side == Side.LONG else -1)
                    )
                    realized += part_pnl
                    allocated_entry_fee = (
                        D(lot.fees) * allocation / D(lot.remaining_qty)
                        if D(lot.remaining_qty)
                        else D(0)
                    )
                    allocations.append(
                        {
                            "link_id": lot.link_id,
                            "qty": str(allocation),
                            "realized_pnl": str(part_pnl),
                            "entry_fee_allocated": str(allocated_entry_fee),
                        }
                    )
                    before_qty = D(lot.remaining_qty)
                    lot.fees = (
                        str(D(lot.fees) * (before_qty - allocation) / before_qty)
                        if before_qty
                        else "0"
                    )
                    lot.remaining_qty = str(before_qty - allocation)
                    parent = await session.get(Order, lot.link_id)
                    if parent and parent.state in {
                        "FILLED",
                        "TP_PENDING",
                        "TP_PARTIALLY_FILLED",
                        "CANCELED",
                    }:
                        next_state = (
                            "CLOSED" if D(lot.remaining_qty) == 0 else "TP_PARTIALLY_FILLED"
                        )
                        parent.state = transition(parent.state, next_state, stale_ok=True)
                        parent.updated_at = utcnow()
                    remaining -= allocation
                    if not remaining:
                        break
                if remaining:
                    raise DatabaseError("Execution chiude quantità non posseduta dal bot")
            payload = {**payload, "_allocations": allocations}
            session.add(
                Execution(
                    exec_id=exec_id,
                    link_id=row.link_id,
                    exchange_id=row.exchange_id,
                    qty=str(qty),
                    price=str(price),
                    fee=str(fee),
                    time_ms=str(payload["execTime"]),
                    realized_pnl=str(realized),
                    purpose=intent.purpose,
                    side=intent.side.value,
                    payload=payload,
                )
            )
            await session.flush()
            return True

    async def executions(self) -> list[dict]:
        async with self.sessions() as session:
            rows = (await session.scalars(select(Execution).order_by(Execution.time_ms))).all()
            return [
                {
                    "exec_id": r.exec_id,
                    "link_id": r.link_id,
                    "qty": r.qty,
                    "price": r.price,
                    "fee": r.fee,
                    "time_ms": r.time_ms,
                    "realized_pnl": r.realized_pnl,
                    "side": r.side,
                    "purpose": r.purpose,
                    "payload": r.payload,
                }
                for r in rows
            ]

    async def lots(self) -> list[dict]:
        async with self.sessions() as session:
            rows = (await session.scalars(select(Lot))).all()
            return [
                {
                    "order_link_id": r.link_id,
                    "side": r.side,
                    "qty": r.remaining_qty,
                    "filled_qty": r.qty,
                    "entry": r.entry,
                    "fees": r.fees,
                    "pair_id": r.pair_id,
                    "purpose": r.purpose,
                }
                for r in rows
                if D(r.remaining_qty) > 0
            ]

    async def put(self, table: str, key: str, payload: dict):
        cls = RECORDS[table]
        async with self.lock, self.sessions.begin() as session:
            row = await session.scalar(select(cls).where(cls.key == key))
            if row:
                row.payload, row.time = payload, utcnow()
            else:
                session.add(cls(key=key, payload=payload, time=utcnow()))

    async def get(self, table: str, key: str) -> dict | None:
        cls = RECORDS[table]
        async with self.sessions() as session:
            row = await session.scalar(select(cls).where(cls.key == key))
            return row.payload if row else None

    async def records(self, table: str, limit: int = 250) -> list[dict]:
        cls = RECORDS[table]
        async with self.sessions() as session:
            rows = (await session.scalars(select(cls).order_by(cls.id.desc()).limit(limit))).all()
            return [{"id": r.id, "key": r.key, "time": r.time, **r.payload} for r in rows]

    async def save_grid(self, snapshot: dict, session_id: str, touch: dict | None = None):
        """Grid sequence claim persisted atomically with audit before any pair is sent."""
        cls = RECORDS["bot_sessions"]
        async with self.lock, self.sessions.begin() as session:
            row = await session.scalar(select(cls).where(cls.key == session_id))
            if row:
                row.payload = snapshot
                row.time = utcnow()
            else:
                session.add(cls(key=session_id, payload=snapshot, time=utcnow()))
            if touch:
                event_cls = RECORDS["strategy_events"]
                session.add(event_cls(key=touch["key"], time=utcnow(), payload=touch))

    async def apply_funding_transaction(self, payload: dict) -> bool:
        try:
            amount = D(payload.get("funding", "0"))
            identifier = str(payload["id"])
            timestamp = str(payload["transactionTime"])
            if not identifier or not timestamp.isdigit() or not amount.is_finite():
                raise ValueError("Funding identificatori/valori non validi")
            if payload.get("symbol") != "BTCUSDT" or payload.get("currency") != "USDT":
                raise ValueError("Funding namespace incoerente")
        except (ValueError, KeyError, ArithmeticError) as exc:
            raise DatabaseError("Funding transaction non valida") from exc
        if not amount:
            return False
        side = {"Buy": "LONG", "Sell": "SHORT"}.get(payload.get("side"))
        async with self.lock, self.sessions.begin() as session:
            existing = await session.get(FundingEvent, identifier)
            if existing:
                if existing.amount != str(amount) or existing.time_ms != timestamp:
                    raise DatabaseError("Funding transaction ID con dati contraddittori")
                return False
            session.add(
                FundingEvent(
                    transaction_id=identifier,
                    amount=str(amount),
                    time_ms=timestamp,
                    side=side,
                    payload=payload,
                )
            )
            return True

    async def funding_events(self) -> list[dict]:
        async with self.sessions() as session:
            rows = (await session.scalars(select(FundingEvent))).all()
            return [
                {"id": r.transaction_id, "amount": r.amount, "time_ms": r.time_ms, "side": r.side}
                for r in rows
            ]

    async def put_batch(self, items: list[tuple[str, str, dict]]):
        async with self.lock, self.sessions.begin() as session:
            for table, key, payload in items:
                cls = RECORDS[table]
                row = await session.scalar(select(cls).where(cls.key == key))
                if row:
                    row.payload, row.time = payload, utcnow()
                else:
                    session.add(cls(key=key, payload=payload, time=utcnow()))
