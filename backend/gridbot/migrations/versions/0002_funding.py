"""Immutable funding ledger; never infer it from trading cashFlow."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "funding_events",
        sa.Column("transaction_id", sa.String(), primary_key=True),
        sa.Column("amount", sa.String(), nullable=False),
        sa.Column("time_ms", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade():
    raise RuntimeError("Downgrade disabled to retain funding audit")
