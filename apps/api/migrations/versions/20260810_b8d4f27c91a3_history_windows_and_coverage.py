"""history windows and coverage.

How far back a kind's synced coverage reaches (ticket 40, ADR-0008): a
successful sync of a bounded-lookback adapter stamps the earliest instant its
window could see, and repeated syncs only ever move it earlier — coverage once
achieved is never un-claimed by a later run. NULL means no bounded coverage
has been claimed: never synced, or a venue whose history is unbounded.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f27c91a3"
down_revision: str | None = "a7c31f92e4b8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connection_adapter_status",
        sa.Column("covered_from", sa.TIMESTAMP(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("connection_adapter_status", "covered_from")
