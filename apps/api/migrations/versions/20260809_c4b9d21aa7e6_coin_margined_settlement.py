"""coin margined settlement.

An inverse contract settles in the coin rather than a quote currency
(ticket 29), and two schema facts follow.

`futures_fill` gains `inverse`: whether the fill belongs to a coin-margined
contract, stated by the port — NULL means the port did not say, and such a
stream is refused at derivation rather than assumed linear. It is
tax-relevant: the documented net accounting states a result in the quote
currency, which for an inverse contract is the wrong unit entirely, so
derivation insists on the variant being stated and, for an inverse stream,
on venue-stated per-fill results. Rows predating this column were imported
while every pipeline was linear-only, so they backfill to false rather
than being retroactively refused.

`tax_lot.leg_id` becomes nullable: a coin-margined close mints a lot for
the settlement asset, and that acquisition has no in-leg — the close is the
futures store's statement, not the transaction ledger's. Identity stays
derived, never assigned: a leg-minted lot keys on (leg_id, ordinal) as
before; a settlement lot keys on where and when it settled —
(account_id, instrument_id, acquired_at, ordinal). No foreign key points at
`futures_position`: derived position rows are wiped and re-inserted
wholesale on every sync, and a cascade from churning ids would silently
empty the materialisation without moving its fingerprint.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4b9d21aa7e6"
down_revision: str | None = "3e8a5b21c4d7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "futures_fill",
        sa.Column("inverse", sa.Boolean, server_default=sa.false()),
    )
    # The backfill was the default's only job; new rows must state the
    # variant or honestly carry NULL, never inherit linear.
    op.alter_column("futures_fill", "inverse", server_default=None)
    op.drop_constraint("tax_lot_pkey", "tax_lot")
    op.alter_column("tax_lot", "leg_id", nullable=True)
    op.create_index(
        "tax_lot_leg_key",
        "tax_lot",
        ["leg_id", "ordinal"],
        unique=True,
        postgresql_where=sa.text("leg_id IS NOT NULL"),
    )
    op.create_index(
        "tax_lot_settlement_key",
        "tax_lot",
        ["account_id", "instrument_id", "acquired_at", "ordinal"],
        unique=True,
        postgresql_where=sa.text("leg_id IS NULL"),
    )
    # A settlement lot's basis is the market value at the close — the same
    # figure, at the same instant, the Section 20 Event states.
    op.create_check_constraint(
        "tax_lot_settlement_at_market_value",
        "tax_lot",
        "leg_id IS NOT NULL OR basis_source = 'market_value'",
    )


def downgrade() -> None:
    op.drop_constraint("tax_lot_settlement_at_market_value", "tax_lot")
    op.drop_index("tax_lot_settlement_key", "tax_lot")
    op.drop_index("tax_lot_leg_key", "tax_lot")
    # The rows a leg never minted cannot survive the key coming back.
    op.execute("DELETE FROM tax_lot WHERE leg_id IS NULL")
    op.alter_column("tax_lot", "leg_id", nullable=False)
    op.create_primary_key("tax_lot_pkey", "tax_lot", ["leg_id", "ordinal"])
    op.drop_column("futures_fill", "inverse")
