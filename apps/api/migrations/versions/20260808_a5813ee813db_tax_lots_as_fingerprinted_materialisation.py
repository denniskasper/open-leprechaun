"""tax lots as fingerprinted materialisation.

Tax Lots are derived in full from the transaction ledger — the only source of
truth (ADR-0014) — and stored here only so holdings and reports need not
replay the ledger on every request. A lot's identity is the in-leg that minted
it: derived rather than assigned, so two rebuilds over unchanged inputs
produce literally identical rows, and following its leg by cascade so the
cache can never block a ledger edit — a deleted Transaction takes its lots
with it, and the fingerprint mismatch marks the survivors for rebuild.

`basis_eur` may be NULL: a basis awaiting valuation — a crypto-crypto trade,
income at market value — until the rate tickets (17, 18) can state it in the
numéraire. `basis_source` says how the basis was, or will be, determined:
`cost` from what left plus the fees charged against the acquisition,
`market_value` on receipt, `estimate` from an Opening Balance's declaration
(always present, that being the declaration's point), `without_consideration`
a windfall's zero — kept, but no Anschaffung.

`input_fingerprint` records, per subject and input class, the count and
digest of the inputs a materialisation was derived from
(repositories/fingerprints.py holds the class vocabulary). A subject whose
stored fingerprint no longer matches the current inputs is detectably stale
rather than quietly wrong — the mechanism the report lifecycle (ticket 23)
deliberately reuses rather than duplicates.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5813ee813db"
down_revision: str | None = "fc41e1dbaccd"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

BASIS_SOURCES = ("cost", "market_value", "estimate", "without_consideration")


def upgrade() -> None:
    quoted_sources = ", ".join(f"'{name}'" for name in BASIS_SOURCES)
    op.create_table(
        "tax_lot",
        sa.Column(
            "leg_id",
            sa.Integer,
            sa.ForeignKey("transaction_leg.id", ondelete="CASCADE", name="tax_lot_leg_fk"),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="CASCADE", name="tax_lot_account_fk"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey("instrument.id", ondelete="CASCADE", name="tax_lot_instrument_fk"),
            nullable=False,
        ),
        sa.Column("acquired_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("quantity", sa.Numeric, nullable=False),
        sa.Column("basis_eur", sa.Numeric),
        sa.Column("basis_source", sa.Text, nullable=False),
        sa.CheckConstraint("quantity > 0", name="tax_lot_positive_quantity"),
        sa.CheckConstraint("basis_eur >= 0", name="tax_lot_basis_not_negative"),
        sa.CheckConstraint(f"basis_source IN ({quoted_sources})", name="tax_lot_basis_sources"),
        sa.CheckConstraint(
            # Spelled out so a NULL basis cannot slip past the comparison.
            "basis_source <> 'without_consideration' OR (basis_eur IS NOT NULL AND basis_eur = 0)",
            name="tax_lot_windfall_costs_nothing",
        ),
        sa.CheckConstraint(
            "basis_source <> 'estimate' OR basis_eur IS NOT NULL",
            name="tax_lot_estimate_carries_basis",
        ),
    )
    # FIFO consumption (ticket 21) walks lots per Account and Instrument in
    # acquisition order; holdings (ticket 20) group along the same edge.
    op.create_index(
        "tax_lot_fifo", "tax_lot", ["account_id", "instrument_id", "acquired_at", "leg_id"]
    )
    op.create_table(
        "input_fingerprint",
        sa.Column("subject", sa.Text, primary_key=True),
        sa.Column("input_class", sa.Text, primary_key=True),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("digest", sa.Text, nullable=False),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("row_count >= 0", name="input_fingerprint_count_not_negative"),
        # SHA-256, as lowercase hex.
        sa.CheckConstraint("digest ~ '^[0-9a-f]{64}$'", name="input_fingerprint_digest_shape"),
    )


def downgrade() -> None:
    op.drop_table("input_fingerprint")
    op.drop_table("tax_lot")
