"""allowance used at source.

How much of the Sparerpauschbetrag a Freistellungsauftrag used at one
Platform in one Tax Year (issue 28), exactly as the institution's annual tax
certificate states it — one row per Platform and year, never derived from the
ledger. The amount lodged with the Platform stays where it is: what was lodged
and what was used are two different facts.

Whether a Platform's kind can carry the figure is the service's judgement,
not a constraint here, so a change of withholding behaviour never disturbs
what a past year's certificate said. The Platform reference restricts
deletion: removing a Platform must never silently change a past year's tax.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4e9c2f7b815"
down_revision: str | None = "f2a6c8d4e1b7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "allowance_used",
        sa.Column(
            "platform_id",
            sa.Integer,
            sa.ForeignKey("platform.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("year", sa.Integer, primary_key=True),
        sa.Column("amount_eur", sa.Numeric(14, 2), nullable=False),
        sa.CheckConstraint("amount_eur >= 0", name="allowance_used_not_negative"),
    )


def downgrade() -> None:
    op.drop_table("allowance_used")
