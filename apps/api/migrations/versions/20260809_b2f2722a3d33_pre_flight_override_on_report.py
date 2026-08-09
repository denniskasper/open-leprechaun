"""pre-flight override on report.

Finalisation refuses while a pre-flight blocker stands open (ticket 25). The
Admin may override with an acknowledgement, and the override is recorded on
the report itself: the acknowledgement verbatim, and the blockers it
overrode frozen as JSON — so every surface showing the report can say it was
finalised over named, counted objections. The two travel together, only on a
final report, and an acknowledgement is never blank.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "b2f2722a3d33"
down_revision: str | None = "5f6b38af3a48"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("report", sa.Column("override_acknowledgement", sa.Text))
    op.add_column("report", sa.Column("overridden_blockers", JSONB))
    op.create_check_constraint(
        "report_override_travels_whole",
        "report",
        "(override_acknowledgement IS NULL) = (overridden_blockers IS NULL)",
    )
    op.create_check_constraint(
        "report_override_only_when_final",
        "report",
        "override_acknowledgement IS NULL OR status = 'final'",
    )
    op.create_check_constraint(
        "report_acknowledgement_not_blank",
        "report",
        "override_acknowledgement IS NULL OR btrim(override_acknowledgement) <> ''",
    )


def downgrade() -> None:
    op.drop_constraint("report_acknowledgement_not_blank", "report")
    op.drop_constraint("report_override_only_when_final", "report")
    op.drop_constraint("report_override_travels_whole", "report")
    op.drop_column("report", "overridden_blockers")
    op.drop_column("report", "override_acknowledgement")
