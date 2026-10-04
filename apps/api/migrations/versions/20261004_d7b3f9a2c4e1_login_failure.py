"""login failure.

The count behind login throttling (ADR-0015): one row per source address that
has failed a login, appearing with its first failure and going when that
address logs in or the record goes stale. In the database rather than in
memory, so a restart is not a free reset and every worker shares one count.

`delayed_until` is when the address may next attempt — a delay, never a lock:
nothing here can keep the right password out once it has passed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7b3f9a2c4e1"
down_revision: str | None = "c5f8d2e1a947"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_failure",
        sa.Column("address", sa.Text, primary_key=True),
        sa.Column("failures", sa.Integer, nullable=False),
        sa.Column("delayed_until", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("failures > 0", name="login_failure_counts_a_failure"),
    )


def downgrade() -> None:
    op.drop_table("login_failure")
