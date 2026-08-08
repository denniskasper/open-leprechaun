"""${message}."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: Sequence[str] | None = ${repr(branch_labels)}
depends_on: Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    # A migration that cannot be reversed must say so explicitly: raise
    # NotImplementedError("<the manual reversal, step by step>") here, and
    # adjust the walk in tests/test_migrations.py to turn back above it.
    ${downgrades if downgrades else "pass"}
