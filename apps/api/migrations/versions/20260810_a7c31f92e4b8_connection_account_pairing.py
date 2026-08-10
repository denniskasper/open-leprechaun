"""connection account pairing.

Which Account each adapter kind of a Connection writes into (ADR-0004):
pairing is configuration and stays apart from the per-kind results in
connection_adapter_status. One Account per (connection, kind) — the unique
constraint is the arbiter, and pairing again moves the kind. An Account or
Connection that goes takes its pairings along; the next sync then says the
kind is unpaired rather than writing anywhere surprising.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c31f92e4b8"
down_revision: str | None = "dee230eb24c5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connection_account",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer,
            sa.ForeignKey("connection.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The adapter kind this pairing serves — vocabulary, not a foreign
        # key, for the same reason connection.venue is unconstrained: a new
        # kind is a registry matter, never a migration.
        sa.Column("adapter_kind", sa.Text, nullable=False),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "connection_id", "adapter_kind", name="connection_account_one_per_kind"
        ),
    )


def downgrade() -> None:
    op.drop_table("connection_account")
