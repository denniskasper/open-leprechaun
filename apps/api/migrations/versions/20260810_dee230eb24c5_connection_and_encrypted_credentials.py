"""connection and encrypted credentials.

A Connection is the single credentialed link to one venue account (ADR-0004):
one key and secret, plus a passphrase where a venue requires one, held as a
single ciphertext column — only ciphertext ever reaches the database
(ADR-0003). The fingerprint is a short digest of the API key so the Admin can
recognise a credential that is never displayed again. Several Connections to
the same Platform are a normal state, told apart by label.

Test and sync results live per adapter kind in connection_adapter_status,
because one kind failing must never hide another succeeding — the health
panel reads this table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dee230eb24c5"
down_revision: str | None = "4d7e91c3a8b2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connection",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        # RESTRICT, not CASCADE: a Platform still holding a credentialed link
        # refuses to go, the same stance Accounts take.
        sa.Column(
            "platform_id",
            sa.Integer,
            sa.ForeignKey("platform.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Which venue implementation this credential speaks to — a registry
        # key, deliberately unconstrained here so a new venue is a registry
        # entry, never a migration.
        sa.Column("venue", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        # AES-GCM ciphertext of the whole credential set under a key derived
        # from the application secret. No plaintext column exists to forget
        # to encrypt.
        sa.Column("credentials_ciphertext", sa.LargeBinary, nullable=False),
        # Digest of the API key, safe to show — the only recognisable trace
        # a credential leaves.
        sa.Column("fingerprint", sa.Text, nullable=False),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "platform_id", "label", name="connection_one_per_label_within_platform"
        ),
    )
    op.create_table(
        "connection_adapter_status",
        # CASCADE: a status row is a report about its Connection and has no
        # life of its own.
        sa.Column(
            "connection_id",
            sa.Integer,
            sa.ForeignKey("connection.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("adapter_kind", sa.Text, primary_key=True),
        sa.Column("last_success_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_error_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_error", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("connection_adapter_status")
    op.drop_table("connection")
