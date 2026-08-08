"""balanced leg transactions.

A Transaction is one economic event recorded as a set of legs that balance —
what left, what arrived, what a fee consumed (ADR-0011). The other side of a
trade is structural rather than conventional, so a buy carries both the asset
acquired and the cash spent, and more than two legs are expressible: a fee in
a third asset is not a special case.

A leg's direction is its role — in, out, or fee — never a sign convention, so
quantities are strictly positive NUMERIC: exact fixed-point, as every monetary
and quantity value in this schema. A fee is its own leg, distinguished so it
is never double-counted, and it may attach to the sibling leg it was charged
against — the composite foreign key over (charged_against_leg_id,
transaction_id) keeps the attachment inside the same Transaction, and a CHECK
keeps it to fee legs alone.

Legs follow their Transaction by cascade — they mean nothing without it — but
an Account or Instrument with ledger entries behind it is refused removal:
the ledger is the only truth, and nothing it rests on may vanish from under
it. The type vocabulary is pinned by a CHECK; which legs each type requires
is the service's decision, and each type's tax consequence is documented in
services/tax_treatment.py, which the tax engines alone will read.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "75e168a8a7ca"
down_revision: str | None = "f174c0d95c06"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

TRANSACTION_TYPES = (
    "trade",
    "transfer_in",
    "transfer_out",
    "spend",
    "staking_reward",
    "lending_interest",
    "mining_reward",
    "airdrop",
    "dividend",
    "distribution",
    "interest",
    "fee",
)


def upgrade() -> None:
    quoted_types = ", ".join(f"'{name}'" for name in TRANSACTION_TYPES)
    op.create_table(
        "transaction",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("type", sa.Text, nullable=False),
        # An absolute instant; tax years are bucketed by German local date
        # later, but the record itself is timezone-independent.
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(f"type IN ({quoted_types})", name="transaction_types"),
    )
    op.create_table(
        "transaction_leg",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.Integer,
            sa.ForeignKey(
                "transaction.id", ondelete="CASCADE", name="transaction_leg_transaction_fk"
            ),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="RESTRICT", name="transaction_leg_account_fk"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="RESTRICT", name="transaction_leg_instrument_fk"
            ),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("quantity", sa.Numeric, nullable=False),
        sa.Column("charged_against_leg_id", sa.Integer),
        sa.CheckConstraint("role IN ('in', 'out', 'fee')", name="transaction_leg_roles"),
        sa.CheckConstraint("quantity > 0", name="transaction_leg_positive_quantity"),
        sa.CheckConstraint(
            "charged_against_leg_id IS NULL OR role = 'fee'",
            name="transaction_leg_only_fees_attach",
        ),
        sa.CheckConstraint("charged_against_leg_id != id", name="transaction_leg_no_self_charge"),
        # The pair every leg is unique on, so the fee attachment below can
        # demand its target sit in the same Transaction.
        sa.UniqueConstraint("id", "transaction_id", name="transaction_leg_within_transaction"),
        sa.ForeignKeyConstraint(
            ["charged_against_leg_id", "transaction_id"],
            ["transaction_leg.id", "transaction_leg.transaction_id"],
            name="transaction_leg_fee_attachment",
        ),
    )
    op.create_index("transaction_leg_by_transaction", "transaction_leg", ["transaction_id"])


def downgrade() -> None:
    op.drop_table("transaction_leg")
    op.drop_table("transaction")
