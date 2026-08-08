"""report lifecycle and staleness.

A Report freezes the figures of one Tax Year at the moment the Admin
generates it (ticket 23): the computed figures land in `figures` as JSON, and
the fingerprint of the inputs that produced them lands in `input_fingerprint`
under the report's own subject (`report:<id>`) — the same mechanism that
guards the Tax Lot materialisation (ADR-0014), deliberately reused rather
than duplicated. A report whose stored fingerprint no longer matches the
current inputs is stale: the frozen figures stand untouched, and every
surface showing them says what moved.

The lifecycle is draft → final, one way: `status` flips exactly once, carries
its instant, and nothing ever updates `figures` or `year` — regenerating is a
new row. No foreign keys leave this table: a report survives the deletion of
anything it was computed from, because a filed figure must outlive its
inputs; the fingerprint mismatch is what says they moved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "de4c4b8bf5d8"
down_revision: str | None = "9c22d1a4f0e7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

STATUSES = ("draft", "final")


def upgrade() -> None:
    quoted_statuses = ", ".join(f"'{status}'" for status in STATUSES)
    op.create_table(
        "report",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finalised_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("figures", JSONB, nullable=False),
        sa.CheckConstraint(f"status IN ({quoted_statuses})", name="report_status_vocabulary"),
        # The instant and the status are one fact: final carries when, draft
        # carries nothing.
        sa.CheckConstraint(
            "(status = 'final') = (finalised_at IS NOT NULL)",
            name="report_final_carries_its_instant",
        ),
        # The same era bound the statutory store enforces: an earlier year is
        # a typo, not history this application computes.
        sa.CheckConstraint("year >= 2009", name="report_year_in_regime"),
    )


def downgrade() -> None:
    op.drop_table("report")
