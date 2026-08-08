"""fx conversion by reference rate.

`reference_rate` stores the euro foreign exchange reference rates as the ECB
publishes them — units of currency per one euro, one row per currency and the
date the rate represents (ticket 17, ADR-0017). A NULL rate records a
**checked absence**: a past date the ECB published nothing for (weekend,
TARGET closing day), so the fallback rule can answer from the store instead
of asking the source again. A stored row is immutable either way: the service
inserts with ON CONFLICT DO NOTHING, so a re-fetch can never change a figure
a past conversion produced. The euro itself is refused — the reference-rate
universe quotes other currencies against it.

`instrument.pegged_currency` marks a stablecoin with the fiat currency it
tracks, so its EUR value comes from that currency's daily reference rate
rather than a crypto price provider — provider coverage of stablecoins is
poor, and an unpriced disposal manufactures a phantom loss. Only the crypto
family carries a peg; a fiat currency does not peg, it is.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "115694893eed"
down_revision: str | None = "43bbb4857d4f"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reference_rate",
        sa.Column("currency", sa.Text, primary_key=True),
        sa.Column("rate_date", sa.Date, primary_key=True),
        # NULL is a checked absence — no publication for this date.
        sa.Column("rate", sa.Numeric),
        sa.Column(
            "fetched_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("rate IS NULL OR rate > 0", name="reference_rate_is_positive"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="reference_rate_currency_is_a_code"),
        sa.CheckConstraint("currency <> 'EUR'", name="reference_rate_quotes_against_the_euro"),
    )
    op.add_column("instrument", sa.Column("pegged_currency", sa.Text))
    op.create_check_constraint(
        "instrument_only_crypto_pegs",
        "instrument",
        "pegged_currency IS NULL OR family = 'crypto'",
    )
    op.create_check_constraint(
        "instrument_peg_is_a_currency_code",
        "instrument",
        "pegged_currency IS NULL OR pegged_currency ~ '^[A-Z]{3}$'",
    )


def downgrade() -> None:
    op.drop_constraint("instrument_peg_is_a_currency_code", "instrument")
    op.drop_constraint("instrument_only_crypto_pegs", "instrument")
    op.drop_column("instrument", "pegged_currency")
    op.drop_table("reference_rate")
