"""deployments.

A token its issuer mints natively on several chains is one Instrument, and
each chain's contract is a Deployment of it (ADR-0032). Identity is
resolved here, under a unique index over chain and lowercased contract, so
one contract still names one Instrument across every chain. The row keeps the
chain and contract it was created with as its home Deployment — the one
prices are asked for, and the label it is shown under — and keeps its own
unique index over it.

Purely structural: every token row becomes an Instrument with one
Deployment, and nothing is merged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7c2b9d813"
down_revision: str | None = "d7e1f3a9c264"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deployment",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey("instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chain", sa.Text, nullable=False),
        sa.Column("contract_address", sa.Text, nullable=False),
    )
    op.create_index(
        "deployment_identity",
        "deployment",
        [sa.text("chain"), sa.text("lower(contract_address)")],
        unique=True,
    )
    op.create_index("deployment_by_instrument", "deployment", ["instrument_id"])
    op.execute(
        "INSERT INTO deployment (instrument_id, chain, contract_address)"
        " SELECT id, chain, contract_address FROM instrument"
        " WHERE family = 'crypto' AND type = 'token' ORDER BY id"
    )


def downgrade() -> None:
    op.drop_table("deployment")
