"""self transfer matching.

Moving assets between the Admin's own Accounts is not a sale and a fresh
purchase. `transfer_match` records the Admin's decision over one proposed
pair — the out-leg of a `transfer_out` and the in-leg of a `transfer_in` —
as `confirmed` or `rejected`. Candidates are derived queries, never rows:
absence of a decision means nobody has looked yet, and a rejected pair is
simply never proposed again. Nothing links itself — every row is a
deliberate act.

A leg belongs to at most one confirmed match per side (partial unique
indexes), while any number of rejections may accumulate; one decision per
pair keeps confirm and reject from contradicting each other. Decisions
follow their legs by cascade: revising a Transaction swaps its legs, so the
match honestly returns to unmatched rather than pointing at quantities the
Admin never confirmed.

The lot engine carries a confirmed transfer's source lots across to the
destination, and one in-leg may then carry several lots — the moved parcel
can span acquisitions with different dates and bases, and merging them would
forge an acquisition date. `tax_lot` therefore gains an `ordinal` and is
keyed on (leg_id, ordinal): identity is still derived, never assigned. The
lot cache is deleted rather than migrated — it is a cache, and clearing the
fingerprint marks it for rebuild on the next read.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "43bbb4857d4f"
down_revision: str | None = "a5813ee813db"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transfer_match",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "out_leg_id",
            sa.Integer,
            sa.ForeignKey(
                "transaction_leg.id", ondelete="CASCADE", name="transfer_match_out_leg_fk"
            ),
            nullable=False,
        ),
        sa.Column(
            "in_leg_id",
            sa.Integer,
            sa.ForeignKey(
                "transaction_leg.id", ondelete="CASCADE", name="transfer_match_in_leg_fk"
            ),
            nullable=False,
        ),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column(
            "decided_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("verdict IN ('confirmed', 'rejected')", name="transfer_match_verdicts"),
        sa.CheckConstraint("out_leg_id <> in_leg_id", name="transfer_match_two_legs"),
        sa.UniqueConstraint("out_leg_id", "in_leg_id", name="transfer_match_one_decision_per_pair"),
    )
    op.create_index(
        "transfer_match_out_leg_once_confirmed",
        "transfer_match",
        ["out_leg_id"],
        unique=True,
        postgresql_where=sa.text("verdict = 'confirmed'"),
    )
    op.create_index(
        "transfer_match_in_leg_once_confirmed",
        "transfer_match",
        ["in_leg_id"],
        unique=True,
        postgresql_where=sa.text("verdict = 'confirmed'"),
    )
    # The lot cache is derived; empty it rather than migrate it, and clear its
    # fingerprint so the next read rebuilds under the new key.
    op.execute("DELETE FROM tax_lot")
    op.execute("DELETE FROM input_fingerprint WHERE subject = 'tax_lots'")
    op.add_column("tax_lot", sa.Column("ordinal", sa.Integer, nullable=False))
    op.create_check_constraint("tax_lot_ordinal_not_negative", "tax_lot", "ordinal >= 0")
    op.drop_constraint("tax_lot_pkey", "tax_lot")
    op.create_primary_key("tax_lot_pkey", "tax_lot", ["leg_id", "ordinal"])
    # FIFO consumption (21) breaks acquisition-instant ties on the derived
    # key, which now includes the ordinal.
    op.drop_index("tax_lot_fifo", "tax_lot")
    op.create_index(
        "tax_lot_fifo",
        "tax_lot",
        ["account_id", "instrument_id", "acquired_at", "leg_id", "ordinal"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM tax_lot")
    op.execute("DELETE FROM input_fingerprint WHERE subject = 'tax_lots'")
    op.drop_index("tax_lot_fifo", "tax_lot")
    op.drop_constraint("tax_lot_pkey", "tax_lot")
    op.drop_constraint("tax_lot_ordinal_not_negative", "tax_lot")
    op.drop_column("tax_lot", "ordinal")
    op.create_primary_key("tax_lot_pkey", "tax_lot", ["leg_id"])
    op.create_index(
        "tax_lot_fifo", "tax_lot", ["account_id", "instrument_id", "acquired_at", "leg_id"]
    )
    op.drop_table("transfer_match")
