from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Order(Base):
    __tablename__ = "orders"
    link_id = Column(String(36), primary_key=True)
    exchange_id = Column(String, unique=True, nullable=True)
    state = Column(String, nullable=False)
    intent = Column(JSON, nullable=False)
    executed_qty = Column(String, nullable=False, default="0")
    executed_notional = Column(String, nullable=False, default="0")
    fees = Column(String, nullable=False, default="0")
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    error = Column(Text, nullable=True)


class Execution(Base):
    __tablename__ = "executions"
    exec_id = Column(String, primary_key=True)
    link_id = Column(String(36), ForeignKey("orders.link_id"), nullable=False)
    exchange_id = Column(String, nullable=False)
    qty = Column(String, nullable=False)
    price = Column(String, nullable=False)
    fee = Column(String, nullable=False)
    time_ms = Column(String, nullable=False)
    realized_pnl = Column(String, nullable=False, default="0")
    purpose = Column(String, nullable=False)
    side = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)


class Lot(Base):
    __tablename__ = "trade_lots"
    link_id = Column(String(36), ForeignKey("orders.link_id"), primary_key=True)
    side = Column(String, nullable=False)
    qty = Column(String, nullable=False)
    remaining_qty = Column(String, nullable=False)
    entry = Column(String, nullable=False)
    fees = Column(String, nullable=False)
    pair_id = Column(String, nullable=True)
    purpose = Column(String, nullable=False)


class RecordMixin:
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False)
    time = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)


class BotSession(RecordMixin, Base):
    __tablename__ = "bot_sessions"


class GridLevelRecord(RecordMixin, Base):
    __tablename__ = "grid_levels"


class PositionRecord(RecordMixin, Base):
    __tablename__ = "positions"


class TakeProfitRecord(RecordMixin, Base):
    __tablename__ = "take_profits"


class RecoveryBlock(RecordMixin, Base):
    __tablename__ = "recovery_blocks"


class Injection(RecordMixin, Base):
    __tablename__ = "injections"


class AccountSnapshot(RecordMixin, Base):
    __tablename__ = "account_snapshots"


class PnlSnapshot(RecordMixin, Base):
    __tablename__ = "pnl_snapshots"


class StrategyEvent(RecordMixin, Base):
    __tablename__ = "strategy_events"


class ErrorRecord(RecordMixin, Base):
    __tablename__ = "errors"


class Configuration(RecordMixin, Base):
    __tablename__ = "configuration"


RECORDS = {
    m.__tablename__: m
    for m in [
        BotSession,
        GridLevelRecord,
        PositionRecord,
        TakeProfitRecord,
        RecoveryBlock,
        Injection,
        AccountSnapshot,
        PnlSnapshot,
        StrategyEvent,
        ErrorRecord,
        Configuration,
    ]
}


class FundingEvent(Base):
    __tablename__ = "funding_events"
    transaction_id = Column(String, primary_key=True)
    amount = Column(String, nullable=False)
    time_ms = Column(String, nullable=False)
    side = Column(String, nullable=True)
    payload = Column(JSON, nullable=False)
