"""platform and account.

A Platform is any place that holds value, distinguished by kind — exchange,
cold storage, software wallet, broker, bank — so a new venue type is a row,
never a new hierarchy. A name is unique within its kind rather than globally,
because one brand may be a bank and a broker both, and those are two places.
An Account is one holding under exactly one Platform (the foreign key is NOT
NULL: nothing is locationless) and will be the boundary for FIFO lot matching.
Its address or reference and the software needed to reach it are metadata
columns nothing reads as a data source. Accounts are unique by name within
their Platform and deliberately not by chain: an Account is scoped as finely
as its Platform evidences, so several per Platform and per chain are a normal
state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f174c0d95c06"
down_revision: str | None = "a3d1f6818004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('exchange', 'cold_storage', 'software_wallet', 'broker', 'bank')",
            name="platform_kinds",
        ),
        sa.UniqueConstraint("name", "kind", name="platform_one_per_name_and_kind"),
    )
    op.create_table(
        "account",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        # RESTRICT, not CASCADE: an Account is a FIFO boundary with holdings
        # behind it, so removing the place it sits under must be refused
        # rather than quietly taking the holdings with it.
        sa.Column(
            "platform_id",
            sa.Integer,
            sa.ForeignKey("platform.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        # Where the evidence names a chain, the Account carries it; a broker
        # or bank Account has none.
        sa.Column("chain", sa.Text),
        # Address, IBAN or reference — identification for a human, never a
        # data source anything syncs from.
        sa.Column("external_reference", sa.Text),
        sa.Column("access_software", sa.Text),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("platform_id", "name", name="account_one_per_name_within_platform"),
    )


def downgrade() -> None:
    op.drop_table("account")
    op.drop_table("platform")
