"""futures fills positions funding.

Imported futures activity as ADR-0009 stores it: fills are the immutable
source of truth, deduplicated on source and external identifier — a re-sync
over an overlapping window inserts nothing twice. Positions are a derived
table rebuilt wholesale per source, sharing one row shape with manually
entered positions: `origin` says which, a CHECK ties `source` to derived
rows alone, and nothing else differs — one model, one tax treatment.

Funding is pulled separately from fills and attributed to the position open
for its symbol at the payment timestamp; `position_id` holds that
attribution, a derived link recomputed on every rebuild — SET NULL when its
position is wiped, and NULL is the surfaced state "unattributable", never a
dropped payment. A derivation that cannot reconcile a fill stream — a
reduction exceeding what is open, history the venue no longer returns —
records an issue row instead of guessing (ADR-0009), wiped and rebuilt with
its source's positions.

Amounts are in the contract's settlement currency, referenced as an
Instrument so the reference-rate universe (ADR-0017) can state their EUR
value at emission time; fees may be negative — a maker rebate is money in.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3e8a5b21c4d7"
down_revision: str | None = "7c50a1d64f2e"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "futures_position",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("origin", sa.Text, nullable=False),
        # The per-kind provenance the deriving sync stamps; a manual position
        # has none — the Admin is not a source.
        sa.Column("source", sa.Text),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="RESTRICT", name="futures_position_account_fk"),
            nullable=False,
        ),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        # Total contracts opened over the position's life, not peak exposure.
        sa.Column("quantity", sa.Numeric, nullable=False),
        sa.Column(
            "settlement_instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="RESTRICT", name="futures_position_settlement_fk"
            ),
            nullable=False,
        ),
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # NULL means open — a position that counts in no Tax Year.
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True)),
        # Settlement-currency amounts, kept separately so each is traceable;
        # funding lives on its own rows and the net figure is a read.
        sa.Column("realized", sa.Numeric, nullable=False),
        sa.Column("fees", sa.Numeric, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("origin IN ('manual', 'derived')", name="futures_position_origins"),
        sa.CheckConstraint(
            "(origin = 'derived') = (source IS NOT NULL)",
            name="futures_position_derived_names_source",
        ),
        sa.CheckConstraint("side IN ('long', 'short')", name="futures_position_sides"),
        sa.CheckConstraint("quantity > 0", name="futures_position_positive_quantity"),
        # Equality allowed: a position may open and close on fills sharing
        # one venue timestamp.
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at",
            name="futures_position_closes_after_opening",
        ),
    )
    op.create_index("futures_position_by_source", "futures_position", ["source"])
    op.create_index(
        "futures_position_by_account_symbol", "futures_position", ["account_id", "symbol"]
    )
    op.create_table(
        "futures_fill",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="RESTRICT", name="futures_fill_account_fk"),
            nullable=False,
        ),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("price", sa.Numeric, nullable=False),
        sa.Column("size", sa.Numeric, nullable=False),
        # The fill's trading fee in the settlement currency; negative is a
        # maker rebate, as venues report it.
        sa.Column("fee", sa.Numeric, nullable=False),
        sa.Column(
            "settlement_instrument_id",
            sa.Integer,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT", name="futures_fill_settlement_fk"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # Optional enrichment (ADR-0009): populated by venues that expose it,
        # making derivation exact; NULL means the venue did not say, never a
        # default.
        sa.Column("position_side", sa.Text),
        sa.Column("reduce_only", sa.Boolean),
        sa.Column("realized", sa.Numeric),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="futures_fill_sides"),
        sa.CheckConstraint("price > 0", name="futures_fill_positive_price"),
        sa.CheckConstraint("size > 0", name="futures_fill_positive_size"),
        sa.CheckConstraint(
            "position_side IS NULL OR position_side IN ('long', 'short')",
            name="futures_fill_position_sides",
        ),
        # The deduplication key: what a venue answered once it answers
        # forever, so overlapping sync windows cannot double-count.
        sa.UniqueConstraint("source", "external_id", name="futures_fill_dedupe"),
    )
    op.create_index("futures_fill_by_source", "futures_fill", ["source"])
    op.create_table(
        "funding_payment",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="RESTRICT", name="funding_payment_account_fk"),
            nullable=False,
        ),
        sa.Column("symbol", sa.Text, nullable=False),
        # Signed in the settlement currency: positive received, negative paid.
        sa.Column("amount", sa.Numeric, nullable=False),
        # Optional enrichment, like a fill's: the hedge-mode side the venue
        # says the payment belongs to, letting attribution pick between a
        # long and a short both open. NULL means the venue did not say.
        sa.Column("position_side", sa.Text),
        sa.Column(
            "settlement_instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="RESTRICT", name="funding_payment_settlement_fk"
            ),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # The attribution, recomputed on every rebuild: NULL is surfaced as
        # unattributable, never dropped.
        sa.Column(
            "position_id",
            sa.Integer,
            sa.ForeignKey(
                "futures_position.id", ondelete="SET NULL", name="funding_payment_position_fk"
            ),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "position_side IS NULL OR position_side IN ('long', 'short')",
            name="funding_payment_position_sides",
        ),
        sa.UniqueConstraint("source", "external_id", name="funding_payment_dedupe"),
    )
    op.create_index("funding_payment_by_position", "funding_payment", ["position_id"])
    op.create_table(
        "futures_derivation_issue",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey(
                "account.id", ondelete="RESTRICT", name="futures_derivation_issue_account_fk"
            ),
            nullable=False,
        ),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("position_side", sa.Text),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("futures_derivation_issue_by_source", "futures_derivation_issue", ["source"])


def downgrade() -> None:
    op.drop_table("futures_derivation_issue")
    op.drop_table("funding_payment")
    op.drop_table("futures_fill")
    op.drop_table("futures_position")
