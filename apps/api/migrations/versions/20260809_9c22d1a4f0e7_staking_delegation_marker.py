"""staking delegation marker.

Committing a holding to a validator is not a disposal: ownership never
changes, so it creates no private-sale event and leaves cost basis and the
Haltefrist untouched — only the resulting rewards are taxable (§22,
ticket 22). What varies between chains is location, not tax, so delegation is
recorded as an informational marker per (Instrument, Account) — the same coin
may be delegated in one Account and idle in another, which neither the
Instrument nor the Account alone can express. The marker describes the
present: removing the row means "no longer delegated".

Deliberately not an input class of any materialisation: marking or unmarking
can never change a lot, a holding period or a tax figure.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c22d1a4f0e7"
down_revision: str | None = "115694893eed"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staking_delegation",
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="CASCADE", name="staking_delegation_instrument_fk"
            ),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("account.id", ondelete="CASCADE", name="staking_delegation_account_fk"),
            primary_key=True,
        ),
        # Where it is delegated to — a validator's name, informational prose.
        sa.Column("note", sa.Text, nullable=True),
        sa.Column(
            "marked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("staking_delegation")
