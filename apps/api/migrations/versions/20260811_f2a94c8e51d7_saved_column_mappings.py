"""saved column mappings.

A column mapping (ticket 33) is the Admin's declaration of one file shape —
which column carries which ledger field, the datetime format and timezone,
the delimiter and decimal convention — saved under a name so a recurring
export from an unsupported venue is read the same way every time. The
definition is stored whole as JSON: the port owns its vocabulary, and the
schema holds only the naming.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f2a94c8e51d7"
down_revision: str | None = "b8d4f27c91a3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "column_mapping",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        # The name the Admin saved it under — saving the name again replaces
        # the definition, so one name is always one current declaration.
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("definition", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("column_mapping")
