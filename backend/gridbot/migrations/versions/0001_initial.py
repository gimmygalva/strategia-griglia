"""Initial schema. Keep this migration fixed; changes require a new revision."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "orders",
        sa.Column("link_id", sa.String(36), primary_key=True),
        sa.Column("exchange_id", sa.String(), unique=True, nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("intent", sa.JSON(), nullable=False),
        sa.Column("executed_qty", sa.String(), nullable=False),
        sa.Column("executed_notional", sa.String(), nullable=False),
        sa.Column("fees", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "executions",
        sa.Column("exec_id", sa.String(), primary_key=True),
        sa.Column("link_id", sa.String(36), sa.ForeignKey("orders.link_id"), nullable=False),
        sa.Column("exchange_id", sa.String(), nullable=False),
        sa.Column("qty", sa.String(), nullable=False),
        sa.Column("price", sa.String(), nullable=False),
        sa.Column("fee", sa.String(), nullable=False),
        sa.Column("time_ms", sa.String(), nullable=False),
        sa.Column("realized_pnl", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "trade_lots",
        sa.Column("link_id", sa.String(36), sa.ForeignKey("orders.link_id"), primary_key=True),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.String(), nullable=False),
        sa.Column("remaining_qty", sa.String(), nullable=False),
        sa.Column("entry", sa.String(), nullable=False),
        sa.Column("fees", sa.String(), nullable=False),
        sa.Column("pair_id", sa.String(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=False),
    )
    for name in [
        "bot_sessions",
        "grid_levels",
        "positions",
        "take_profits",
        "recovery_blocks",
        "injections",
        "account_snapshots",
        "pnl_snapshots",
        "strategy_events",
        "errors",
        "configuration",
    ]:
        op.create_table(
            name,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("key", sa.String(), unique=True, nullable=False),
            sa.Column("time", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
        )


def downgrade():
    raise RuntimeError("Downgrade disabled: retain financial audit and execution ledger")
