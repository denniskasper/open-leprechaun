"""portfolio snapshots.

What the portfolio measured on one day (ticket 54): one row per Europe/Berlin
calendar date, replaced by a later run of the same day — so a schedule firing
more than daily, or a run-now, sharpens the day's point instead of adding one.

`value_eur` is the worth of every counted Position and NULL where something
is held but nothing counts — a figure nobody can state, never a zero.
`contributions_eur` and `withdrawals_eur` are cumulative from the beginning
of the ledger as it stood when the snapshot was taken, so the difference
between two snapshots says what was put in and taken out between them, and
`unvalued_flows` is how many such movements nothing stored could value — they
stand outside both sums, counted here so the row says what it leaves out.

A snapshot is a stored observation, not a derivation: it references nothing
and nothing rebuilds it, so a ledger corrected afterwards changes the next
snapshot and never an earlier one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2a4c9d316"
down_revision: str | None = "a9d3e7c15b62"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshot",
        sa.Column("snapshot_date", sa.Date, primary_key=True),
        sa.Column("taken_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("value_eur", sa.Numeric),
        sa.Column("positions_held", sa.Integer, nullable=False),
        sa.Column("positions_counted", sa.Integer, nullable=False),
        sa.Column("contributions_eur", sa.Numeric, nullable=False),
        sa.Column("withdrawals_eur", sa.Numeric, nullable=False),
        sa.Column("unvalued_flows", sa.Integer, nullable=False),
        sa.CheckConstraint(
            "positions_counted BETWEEN 0 AND positions_held",
            name="portfolio_snapshot_counted_within_held",
        ),
        # A value is unstated exactly when something is held and none of it
        # counts; an empty portfolio is worth nothing, which is a figure.
        sa.CheckConstraint(
            "(value_eur IS NULL) = (positions_held > 0 AND positions_counted = 0)",
            name="portfolio_snapshot_value_stated_when_counted",
        ),
        sa.CheckConstraint(
            "contributions_eur >= 0 AND withdrawals_eur >= 0 AND unvalued_flows >= 0",
            name="portfolio_snapshot_flows_not_negative",
        ),
    )


def downgrade() -> None:
    op.drop_table("portfolio_snapshot")
