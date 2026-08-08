"""EUR, the numéraire, born with the schema.

Cash is an Instrument like any other (ADR-0011); what sets the numéraire apart
is a flag, not a symbol comparison anywhere in logic. The schema holds the
designation to at most one row — a partial unique index — and to the cash
family, so another jurisdiction's numéraire is an UPDATE, never a code change.

EUR itself is inserted here rather than seeded: every environment runs the
migration chain, and a deployment needs the numéraire to exist before its
first transaction, while the seed never runs outside development.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3d1f6818004"
down_revision: str | None = "f9fabc91f6e7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "instrument",
        sa.Column("is_numeraire", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "instrument_numeraire_is_cash",
        "instrument",
        "NOT is_numeraire OR family = 'cash'",
    )
    # Every flagged row carries the same value, so unique means at most one.
    op.create_index(
        "instrument_one_numeraire",
        "instrument",
        ["is_numeraire"],
        unique=True,
        postgresql_where=sa.text("is_numeraire"),
    )
    op.execute(
        "INSERT INTO instrument (family, type, symbol, name, is_numeraire)"
        " VALUES ('cash', 'fiat', 'EUR', 'Euro', false)"
        " ON CONFLICT DO NOTHING"
    )
    # Flagged separately so a pre-existing EUR row — possible on a database
    # that minted one through create_cash before this revision — becomes the
    # numéraire rather than leaving the instance without one.
    op.execute("UPDATE instrument SET is_numeraire = true WHERE family = 'cash' AND symbol = 'EUR'")
    op.execute(
        "INSERT INTO instrument_identifier (instrument_id, kind, value)"
        " SELECT id, 'symbol', symbol FROM instrument WHERE family = 'cash'"
        " ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    # Remove the row this revision minted; its identifier history follows by
    # cascade. An EUR row that predated the upgrade is not distinguishable and
    # goes with it — below this revision the schema cannot say "numéraire".
    op.execute("DELETE FROM instrument WHERE family = 'cash' AND symbol = 'EUR'")
    op.drop_index("instrument_one_numeraire", table_name="instrument")
    op.drop_constraint("instrument_numeraire_is_cash", "instrument")
    op.drop_column("instrument", "is_numeraire")
