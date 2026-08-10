"""import framework.

An Import Batch (ticket 31) is one import recorded as a unit and reversible as
a unit: every import previews before it writes, commits as a separate act, and
deduplicates on source and external identifier so re-importing the same file
changes nothing.

`imported_row` is the deduplication registry: one row per imported record,
unique on (source, external_id). The registry row is what makes idempotency
survive the Admin's own hands — a manually edited or deleted imported
Transaction is marked `overridden`, its registry row staying behind as a
tombstone (transaction_id SET NULL on delete), so a re-import counts it a
duplicate rather than silently reverting the correction. Reversing a batch
releases its overridden rows (batch_id goes NULL — the Admin took ownership of
those) and removes everything else with the batch; the CHECKs pin that a row
detached from its batch or its Transaction is only ever such a tombstone.

The Account carries which source is authoritative for it — exactly one
ingestion mode writes per Account; a second source may reconcile but may not
write. NULL means none declared yet; the first committed import declares
itself.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4d7e91c3a8b2"
down_revision: str | None = "85b92c2e37fe"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_batch",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        # The per-kind provenance string the rows were stamped with.
        sa.Column("source", sa.Text, nullable=False),
        # What the Admin imported, in their words — a filename, usually.
        sa.Column("label", sa.Text, nullable=False),
        # RESTRICT, not CASCADE: a batch is the undo unit for ledger entries,
        # so the Account they sit in must not vanish from under it.
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="RESTRICT", name="import_batch_account_fk"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "imported_row",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        # NULL only for an overridden tombstone released by its batch's
        # reversal; live rows follow their batch by cascade.
        sa.Column(
            "batch_id",
            sa.Integer,
            sa.ForeignKey("import_batch.id", ondelete="CASCADE", name="imported_row_batch_fk"),
        ),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        # NULL only for an overridden tombstone whose Transaction the Admin
        # deleted by hand; the SET NULL is what lets the tombstone outlive it.
        sa.Column(
            "transaction_id",
            sa.Integer,
            sa.ForeignKey(
                "transaction.id", ondelete="SET NULL", name="imported_row_transaction_fk"
            ),
        ),
        sa.Column("overridden", sa.Boolean, nullable=False, server_default=sa.false()),
        # The deduplication key: re-importing the same record from the same
        # source changes nothing, whatever became of the row it created.
        sa.UniqueConstraint("source", "external_id", name="imported_row_once_per_source"),
        sa.CheckConstraint(
            "batch_id IS NOT NULL OR overridden", name="imported_row_detached_only_overridden"
        ),
        sa.CheckConstraint(
            "transaction_id IS NOT NULL OR overridden",
            name="imported_row_transactionless_only_overridden",
        ),
    )
    op.create_index("imported_row_by_batch", "imported_row", ["batch_id"])
    op.create_index("imported_row_by_transaction", "imported_row", ["transaction_id"])
    # Exactly one ingestion mode may write into an Account; NULL means none is
    # declared yet, and the first committed import declares itself.
    op.add_column("account", sa.Column("authoritative_source", sa.Text))


def downgrade() -> None:
    op.drop_column("account", "authoritative_source")
    op.drop_table("imported_row")
    op.drop_table("import_batch")
