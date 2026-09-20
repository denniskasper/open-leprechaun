"""capital income and treaty limits.

Income from securities is recorded gross with every tax already taken out of
it (ticket 47). The ledger's in-leg stays what actually arrived — the net —
so cash balances keep balancing; `capital_income` holds what the payer's
statement says beyond that, one row per dividend, distribution or interest
Transaction: the security that paid, the Quellensteuer with its source
country, and the German tax withheld at source split into its components.
Every amount is denominated in the received leg's own Instrument — the
currency the statement was written in — and converts at the event date like
the leg itself (ADR-0017), so the gross is the net plus everything withheld.

A Quellensteuer and its country stand or fall together: creditability depends
on which country withheld (CONTEXT.md), so neither is recorded alone.

`treaty_limit` holds, per source country, the share of a gross dividend the
double-taxation treaty lets that country keep — the ceiling up to which its
Quellensteuer is creditable, anything above being reclaimable there. Like
every statutory figure it is configuration with a cited source, never a
constant in logic; unlike the per-year store it keys on the country alone,
because a treaty article does not move with the calendar.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f7a1d95e08"
down_revision: str | None = "b6e19f4d3a57"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capital_income",
        sa.Column(
            "transaction_id",
            sa.Integer,
            sa.ForeignKey(
                "transaction.id", ondelete="CASCADE", name="capital_income_transaction_fk"
            ),
            primary_key=True,
        ),
        # The security that paid — what selects a fund distribution's
        # Teilfreistellung. RESTRICT, like a leg's Instrument: an Instrument
        # with income recorded against it refuses to go.
        sa.Column(
            "paying_instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="RESTRICT", name="capital_income_paying_instrument_fk"
            ),
            nullable=True,
        ),
        sa.Column("foreign_withholding", sa.Numeric, nullable=False, server_default="0"),
        sa.Column("source_country", sa.Text, nullable=True),
        sa.Column("kapitalertragsteuer", sa.Numeric, nullable=False, server_default="0"),
        sa.Column("solidarity_surcharge", sa.Numeric, nullable=False, server_default="0"),
        sa.Column("church_tax", sa.Numeric, nullable=False, server_default="0"),
        sa.CheckConstraint(
            "foreign_withholding >= 0 AND kapitalertragsteuer >= 0"
            " AND solidarity_surcharge >= 0 AND church_tax >= 0",
            name="capital_income_amounts_are_not_negative",
        ),
        sa.CheckConstraint(
            "source_country IS NULL OR source_country ~ '^[A-Z]{2}$'",
            name="capital_income_source_country_shape",
        ),
        sa.CheckConstraint(
            "(foreign_withholding > 0) = (source_country IS NOT NULL)",
            name="capital_income_withholding_names_its_country",
        ),
    )
    op.create_table(
        "treaty_limit",
        sa.Column("country", sa.Text, primary_key=True),
        sa.Column("rate", sa.Numeric, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.CheckConstraint("country ~ '^[A-Z]{2}$'", name="treaty_limit_country_shape"),
        sa.CheckConstraint("rate >= 0 AND rate <= 1", name="treaty_limit_rate_is_a_fraction"),
        sa.CheckConstraint("btrim(source) <> ''", name="treaty_limit_source_is_cited"),
    )


def downgrade() -> None:
    op.drop_table("treaty_limit")
    op.drop_table("capital_income")
