"""Chain root.

Creates nothing. It exists so the chain has an explicit beginning: the harness
tests walk `base ⇄ head` from the first schema ticket onward, and every later
revision names a parent instead of starting a second head.
"""

from collections.abc import Sequence

revision: str = "d3b78900dbe5"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
