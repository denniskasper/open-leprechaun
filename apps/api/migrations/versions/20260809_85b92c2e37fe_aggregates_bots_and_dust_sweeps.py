"""aggregates bots and dust sweeps.

An Aggregate (ticket 30) is a presentation summary over many tiny records
whose constituents remain retrievable — it is read by no tax engine and
changes no figure. Two kinds: a `bot` names a futures fill source (optionally
narrowed to one symbol) and covers whatever that source's fills derive, so
membership survives the wholesale wipe-and-rebuild of derived positions
(ADR-0009); a `dust_sweep` collects trade Transactions through the nullable
`transaction.aggregate_id`, SET NULL both ways — disbanding an aggregate or
deleting a member never touches the other side.

Membership is deliberately outside the input fingerprint (ADR-0014), like a
note: tagging rows into a summary is presentation and must not mark a report
stale.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "85b92c2e37fe"
down_revision: str | None = "c4b9d21aa7e6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aggregate",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        # A bot's scope: the per-kind provenance string its fills wear,
        # optionally narrowed to one symbol. NULL symbol means the whole
        # source.
        sa.Column("futures_source", sa.Text),
        sa.Column("futures_symbol", sa.Text),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("kind IN ('bot', 'dust_sweep')", name="aggregate_kinds"),
        sa.CheckConstraint(
            "(kind = 'bot') = (futures_source IS NOT NULL)",
            name="aggregate_bot_names_source",
        ),
        sa.CheckConstraint(
            "futures_symbol IS NULL OR kind = 'bot'", name="aggregate_symbol_is_bot_scope"
        ),
    )
    # Exact-duplicate backstop; the service refuses the wider overlaps (a
    # source-wide aggregate beside a symbol-narrowed one) with a sentence.
    op.create_index(
        "aggregate_bot_scope",
        "aggregate",
        ["futures_source", "futures_symbol"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("kind = 'bot'"),
    )
    op.add_column(
        "transaction",
        # Dust-sweep membership: presentation only, so the fingerprint
        # (ADR-0014) deliberately does not cover it — tagging marks nothing
        # stale — and a disbanded aggregate releases its members by SET NULL.
        sa.Column(
            "aggregate_id",
            sa.Integer,
            sa.ForeignKey("aggregate.id", ondelete="SET NULL", name="transaction_aggregate_fk"),
        ),
    )
    op.create_index("transaction_by_aggregate", "transaction", ["aggregate_id"])


def downgrade() -> None:
    op.drop_index("transaction_by_aggregate", table_name="transaction")
    op.drop_column("transaction", "aggregate_id")
    op.drop_table("aggregate")
