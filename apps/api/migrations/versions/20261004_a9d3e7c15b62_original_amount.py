"""original amount.

A broker settles a trade in the Depot's currency whatever the security is
priced in (ticket 48, ADR-0025). The ledger's legs stay what actually moved —
the security and the cash the Depot paid or received — so cash balances keep
reconciling to the broker; `original_amount` holds what the broker's
statement says beside that, one row per such trade: the amount as it was
priced, the currency it was priced in, the rate the broker applied and the
date that rate is of.

The rate is stated the way reference rates are (ADR-0017): units of the
original currency per one unit of the currency the trade settled in. It is
the broker's own rate, recorded so the settled amount can show its working —
never an input a tax figure is computed from.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d3e7c15b62"
down_revision: str | None = "f6b1d4e8a2c7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "original_amount",
        sa.Column(
            "transaction_id",
            sa.Integer,
            sa.ForeignKey(
                "transaction.id", ondelete="CASCADE", name="original_amount_transaction_fk"
            ),
            primary_key=True,
        ),
        sa.Column("amount", sa.Numeric, nullable=False),
        # A currency code as the venue states it — not a foreign key to a cash
        # Instrument, because the Depot never held this currency.
        sa.Column("currency", sa.Text, nullable=False),
        sa.Column("rate", sa.Numeric, nullable=False),
        sa.Column("rate_date", sa.Date, nullable=False),
        sa.CheckConstraint("amount > 0", name="original_amount_is_positive"),
        sa.CheckConstraint("rate > 0", name="original_amount_rate_is_positive"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="original_amount_currency_shape"),
    )


def downgrade() -> None:
    op.drop_table("original_amount")
