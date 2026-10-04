"""connection reconciliation.

What reconciling each Connection last came to (ticket 58): one row per
Connection, appearing with its first reconciliation and replaced by each
later one. A reconciliation still writes nothing to the ledger — this is the
record that it ran, so the first-run checklist can derive "reconciled" from
something that happened rather than from a flag the Admin ticked.

`gaps` counts the lines the run left open — a gap, or a venue symbol no
single Instrument answers to — and `failed_kinds` the adapter kinds that
compared nothing. Both zero is a Connection whose venue and ledger agreed. The row
goes with its Connection.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8c4a1f6b2d9"
down_revision: str | None = "d7b3f9a2c4e1"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connection_reconciliation",
        sa.Column(
            "connection_id",
            sa.Integer,
            sa.ForeignKey("connection.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("reconciled_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("gaps", sa.Integer, nullable=False),
        sa.Column("failed_kinds", sa.Integer, nullable=False),
        sa.CheckConstraint(
            "gaps >= 0 AND failed_kinds >= 0", name="connection_reconciliation_counts_are_counts"
        ),
    )


def downgrade() -> None:
    op.drop_table("connection_reconciliation")
