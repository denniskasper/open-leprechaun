"""crypto prices with fallback chain.

Two stores for what the provider chain (ticket 18) learns. `crypto_price`
holds the last known price per Instrument — one row, overwritten by each
fresh quote, carrying the source that answered and the instant the quote
represents, so a price served after every provider fails can say honestly
how old it is and where it came from. `crypto_daily_close` holds one close
per Instrument and day with the same source attribution; a backfill fills a
chosen range, and the first stored close for a day wins so history never
silently shifts under a chart.

EUR throughout: a provider quoting another currency is converted by the
reference-rate rule before anything is stored (ADR-0017).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5f6b38af3a48"
down_revision: str | None = "de4c4b8bf5d8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crypto_price",
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey("instrument.id", ondelete="CASCADE", name="crypto_price_instrument_fk"),
            primary_key=True,
        ),
        sa.Column("price_eur", sa.Numeric, nullable=False),
        # Which provider answered — the attribution a stale label cites.
        sa.Column("source", sa.Text, nullable=False),
        # The instant the quote represents, per the provider — not fetch time.
        sa.Column("as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("price_eur > 0", name="crypto_price_is_positive"),
    )
    op.create_table(
        "crypto_daily_close",
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="CASCADE", name="crypto_daily_close_instrument_fk"
            ),
            primary_key=True,
        ),
        sa.Column("close_date", sa.Date, primary_key=True),
        sa.Column("price_eur", sa.Numeric, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.CheckConstraint("price_eur > 0", name="crypto_daily_close_is_positive"),
    )


def downgrade() -> None:
    op.drop_table("crypto_daily_close")
    op.drop_table("crypto_price")
