"""stance and the unacknowledged inbox.

The Admin's standing position on an Instrument (ADR-0012): a stance row is a
deliberate act, and its absence is the default — `unacknowledged`, nobody has
looked yet. `dangerous` is one global row (NULL account), because a token whose
approval drains a wallet is dangerous everywhere; `kept` and `ignored` are one
row per Account, which is what lets a genuine holding bought at one venue
coexist with dust of the same Instrument sprayed at another. A CHECK ties the
scope to the stance so the two can never disagree, and partial unique indexes
hold each scope to one decision.

Stance rows follow their Instrument or Account by cascade: unlike a ledger
entry, a stance is the Admin's opinion about a thing, not a fact the ledger
rests on.

The transaction vocabulary gains `windfall`: what a kept unsolicited inflow
settles as when it was received for no counter-performance — as `airdrop` is
what it settles as when it was (services/stances.py holds that decision).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2b99560def98"
down_revision: str | None = "75e168a8a7ca"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

STANCES = ("kept", "ignored", "dangerous")

TRANSACTION_TYPES = (
    "trade",
    "transfer_in",
    "transfer_out",
    "spend",
    "staking_reward",
    "lending_interest",
    "mining_reward",
    "airdrop",
    "windfall",
    "dividend",
    "distribution",
    "interest",
    "fee",
)


def _pin_transaction_types(types: Sequence[str]) -> None:
    quoted_types = ", ".join(f"'{name}'" for name in types)
    op.drop_constraint("transaction_types", "transaction", type_="check")
    op.create_check_constraint("transaction_types", "transaction", f"type IN ({quoted_types})")


def upgrade() -> None:
    quoted_stances = ", ".join(f"'{name}'" for name in STANCES)
    op.create_table(
        "instrument_stance",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="CASCADE", name="instrument_stance_instrument_fk"
            ),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="CASCADE", name="instrument_stance_account_fk"),
        ),
        sa.Column("stance", sa.Text, nullable=False),
        sa.Column(
            "decided_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(f"stance IN ({quoted_stances})", name="instrument_stance_vocabulary"),
        # The scope IS the stance: global exactly when dangerous.
        sa.CheckConstraint(
            "(account_id IS NULL) = (stance = 'dangerous')", name="instrument_stance_scope"
        ),
    )
    op.create_index(
        "instrument_stance_one_global",
        "instrument_stance",
        ["instrument_id"],
        unique=True,
        postgresql_where=sa.text("account_id IS NULL"),
    )
    op.create_index(
        "instrument_stance_once_per_account",
        "instrument_stance",
        ["instrument_id", "account_id"],
        unique=True,
        postgresql_where=sa.text("account_id IS NOT NULL"),
    )
    _pin_transaction_types(TRANSACTION_TYPES)


def downgrade() -> None:
    # A settled windfall returns to the unclassified inflow it once was; the
    # airdrop settlement survives, since the type predates this migration.
    op.execute("UPDATE transaction SET type = 'transfer_in' WHERE type = 'windfall'")
    _pin_transaction_types(tuple(name for name in TRANSACTION_TYPES if name != "windfall"))
    op.drop_table("instrument_stance")
