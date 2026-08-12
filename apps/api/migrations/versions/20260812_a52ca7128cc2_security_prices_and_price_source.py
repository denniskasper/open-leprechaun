"""security prices and price source.

Two stores for what the securities market-data provider (ticket 45) learns,
mirroring the crypto ones (ticket 18). `security_price` holds the last known
price per Instrument — one row, overwritten by each fresh quote, carrying the
currency and venue the quote was made in, the provider that answered and the
instant the quote represents, so a price served after the provider fails can
say honestly how old it is and where it came from. A non-EUR quote is
converted by the reference-rate rule before storing (ADR-0017); the recorded
quote currency and venue keep the conversion's origin on display.
`security_daily_close` holds one close per Instrument and day with the same
source attribution; the first stored close for a day wins so history never
silently shifts under a chart.

`listing.price_source` names the one Listing whose market prices the
Instrument — the price-source concept ticket 44 left to this ticket. At most
one per Instrument, held by a partial unique index. Existing single listings
are marked on the way up: each was the primary listing of a picked search
candidate, which is exactly the market the picker vouched for.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a52ca7128cc2"
down_revision: str | None = "7eaeeda0c77a"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_price",
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey("instrument.id", ondelete="CASCADE", name="security_price_instrument_fk"),
            primary_key=True,
        ),
        sa.Column("price_eur", sa.Numeric, nullable=False),
        # The currency and venue the quote was made in — a non-EUR quote is
        # stored converted, and these say what it was converted from.
        sa.Column("quote_currency", sa.Text, nullable=False),
        sa.Column("venue", sa.Text, nullable=False),
        # Which provider answered — the attribution a stale label cites.
        sa.Column("source", sa.Text, nullable=False),
        # The instant the quote represents, per the provider — not fetch time.
        sa.Column("as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("price_eur > 0", name="security_price_is_positive"),
    )
    op.create_table(
        "security_daily_close",
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="CASCADE", name="security_daily_close_instrument_fk"
            ),
            primary_key=True,
        ),
        sa.Column("close_date", sa.Date, primary_key=True),
        sa.Column("price_eur", sa.Numeric, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.CheckConstraint("price_eur > 0", name="security_daily_close_is_positive"),
    )
    op.add_column(
        "listing",
        sa.Column("price_source", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "listing_one_price_source_per_instrument",
        "listing",
        ["instrument_id"],
        unique=True,
        postgresql_where=sa.text("price_source"),
    )
    # A security's lone listing was the primary listing of a picked candidate
    # — the one market the picker vouched for, so it becomes the price source.
    op.execute(
        "UPDATE listing SET price_source = true"
        " WHERE instrument_id IN"
        " (SELECT l.instrument_id FROM listing l"
        "  JOIN instrument i ON i.id = l.instrument_id AND i.family = 'security'"
        "  GROUP BY l.instrument_id HAVING count(*) = 1)"
    )


def downgrade() -> None:
    op.drop_index("listing_one_price_source_per_instrument", table_name="listing")
    op.drop_column("listing", "price_source")
    op.drop_table("security_daily_close")
    op.drop_table("security_price")
