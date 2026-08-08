"""admin user and session.

The single admin's credential row and the sessions login mints. `admin_user`
enforces the single-admin invariant in the schema per ADR-0006: `singleton`
is always true under a unique constraint, so a second row cannot exist no
matter how many workers race a fresh database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2be0513ec52b"
down_revision: str | None = "d3b78900dbe5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_user",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "singleton",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
            unique=True,
        ),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("singleton", name="admin_user_is_singular"),
    )
    op.create_table(
        "admin_session",
        # The SHA-256 of the token, so a database dump does not hand out live sessions.
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column(
            "admin_user_id",
            sa.Integer,
            sa.ForeignKey("admin_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("admin_session")
    op.drop_table("admin_user")
