"""network facts.

What a venue or a chain states about the network a transfer moved on — the
ledger's chain, the transaction hash, the address on the other side — kept
beside the Transaction as recorded fact (ADR-0032). It never decides
identity; it lets a reader see where an inflow came from, and lets two sides
of one chain transaction be recognised as one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b8d4c6a917"
down_revision: str | None = "e4a7c2b9d813"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "network_fact",
        sa.Column(
            "transaction_id",
            sa.Integer,
            sa.ForeignKey("transaction.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chain", sa.Text),
        sa.Column("tx_hash", sa.Text),
        sa.Column("counterparty_address", sa.Text),
        sa.CheckConstraint(
            "chain IS NOT NULL OR tx_hash IS NOT NULL OR counterparty_address IS NOT NULL",
            name="network_fact_states_something",
        ),
    )
    op.create_index("network_fact_by_hash", "network_fact", ["tx_hash"])


def downgrade() -> None:
    op.drop_table("network_fact")
