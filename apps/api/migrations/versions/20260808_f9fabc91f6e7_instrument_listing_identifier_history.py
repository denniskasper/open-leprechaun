"""instrument, listing, identifier history.

One Instrument concept over crypto, securities and cash (ADR-0010). Identity
is the schema's job: a token keys on chain and contract address, a native coin
and a cash currency on symbol within their family, a security on ISIN. A
symbol is a display label — nothing constrains it across families, so two
Instruments sharing one coexist. `listing` gives price sources a target that
names venue and quote currency; `instrument_identifier` keeps every identifier
ever attached so a superseded ISIN still resolves.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9fabc91f6e7"
down_revision: str | None = "2be0513ec52b"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instrument",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("family", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("chain", sa.Text),
        sa.Column("contract_address", sa.Text),
        sa.Column("isin", sa.Text),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(family = 'crypto' AND type IN ('native', 'token'))"
            " OR (family = 'security' AND type IN ('share', 'etf', 'fund', 'bond', 'certificate'))"
            " OR (family = 'cash' AND type = 'fiat')",
            name="instrument_type_refines_family",
        ),
        # A token carries its chain and contract; a native coin its chain only.
        sa.CheckConstraint(
            "family <> 'crypto' OR ("
            "chain IS NOT NULL AND (contract_address IS NOT NULL) = (type = 'token'))",
            name="instrument_crypto_carries_its_keys",
        ),
        sa.CheckConstraint(
            "family = 'crypto' OR (chain IS NULL AND contract_address IS NULL)",
            name="instrument_only_crypto_has_chain",
        ),
        sa.CheckConstraint(
            "(family = 'security') = (isin IS NOT NULL)",
            name="instrument_only_securities_have_isin",
        ),
    )
    # Identity, per family. Symbol is deliberately not in the token index —
    # it is a display label, never a key. The contract is compared lowercased
    # in the index itself, so no write path can mint a second identity for the
    # same contract through checksum casing.
    op.create_index(
        "instrument_token_identity",
        "instrument",
        [sa.text("chain"), sa.text("lower(contract_address)")],
        unique=True,
        postgresql_where=sa.text("contract_address IS NOT NULL"),
    )
    op.create_index(
        "instrument_native_coin_identity",
        "instrument",
        ["symbol"],
        unique=True,
        postgresql_where=sa.text("family = 'crypto' AND type = 'native'"),
    )
    op.create_index(
        "instrument_cash_identity",
        "instrument",
        ["symbol"],
        unique=True,
        postgresql_where=sa.text("family = 'cash'"),
    )
    op.create_index(
        "instrument_security_identity",
        "instrument",
        ["isin"],
        unique=True,
        postgresql_where=sa.text("isin IS NOT NULL"),
    )
    op.create_table(
        "listing",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey("instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("venue", sa.Text, nullable=False),
        sa.Column("quote_currency", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "instrument_id", "venue", "quote_currency", name="listing_one_per_market"
        ),
    )
    op.create_table(
        "instrument_identifier",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey("instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        # NULL means current; a superseded identifier stays for resolution.
        sa.Column("superseded_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('isin', 'wkn', 'ticker', 'contract_address', 'symbol')",
            name="instrument_identifier_kinds",
        ),
        sa.UniqueConstraint(
            "instrument_id", "kind", "value", name="instrument_identifier_once_per_instrument"
        ),
    )
    op.create_index("instrument_identifier_by_value", "instrument_identifier", ["value"])


def downgrade() -> None:
    op.drop_table("instrument_identifier")
    op.drop_table("listing")
    op.drop_table("instrument")
