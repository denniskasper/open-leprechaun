"""pending orders.

What a broker last said it holds open for a Depot (Pending Orders): one
observation per Account — when it was asked, the sentence it failed with if
it did, and the cash the broker holds back for those orders — and the orders
themselves beneath it. Each observation replaces the one before; nothing here
is history, so removing the Account takes its observation with it.

A security is recorded as the broker named it, by ISIN, never resolved to an
Instrument: an order may be for a security the ledger has never held.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e1f3a9c264"
down_revision: str | None = "b3d9e6a1f428"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_order_observation",
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("reserved_cash", sa.Numeric(38, 18)),
        sa.Column("reserved_currency", sa.Text),
    )
    op.create_table(
        "pending_order",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("pending_order_observation.account_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("isin", sa.Text, nullable=False),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("order_type", sa.Text, nullable=False),
        sa.Column("currency", sa.Text, nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18)),
        sa.Column("value", sa.Numeric(38, 18)),
        sa.Column("limit_price", sa.Numeric(38, 18)),
        sa.Column("stop_price", sa.Numeric(38, 18)),
        sa.UniqueConstraint("account_id", "external_id"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="pending_order_side_known"),
        sa.CheckConstraint(
            "order_type IN ('market', 'limit', 'stop', 'stop_limit')",
            name="pending_order_type_known",
        ),
        sa.CheckConstraint(
            "(quantity IS NULL) <> (value IS NULL)", name="pending_order_quantity_or_value"
        ),
    )


def downgrade() -> None:
    op.drop_table("pending_order")
    op.drop_table("pending_order_observation")
