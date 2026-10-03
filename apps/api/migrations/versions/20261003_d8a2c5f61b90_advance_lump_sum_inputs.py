"""advance lump sum inputs.

What the Vorabpauschale (§18 InvStG, ticket 53) reads beyond the ledger, all
of it configuration with a cited source and none of it a constant in logic.

The statutory vocabulary gains one required rate, `advance_lump_sum_factor`:
the share of the Basiszins the base yield is computed from (§18 Abs. 1 Satz 2
InvStG). It is keyed, like the Basiszins beside it, by the year the amount
derives from; the known 2024-2026 values ride in with the migration exactly
as the Basiszins did.

`fund_redemption_value` holds, per fund and per year, what the fund itself
published for one unit: the first and the last redemption price of the
calendar year and the distributions within it — the three figures the Anlage
KAP-INV asks for in its lines 33, 35 and 37. They are entered in EUR, never
derived from a market close (CONTEXT.md, Vorabpauschale): a year with no row
for a fund held across it refuses to compute. A distribution of zero is a
statement — a pure accumulator's own answer — so the column is NOT NULL and
carries no default. The rows follow their Instrument by cascade: they are
that fund's configuration and nothing else points at them.
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "d8a2c5f61b90"
down_revision: str | None = "c3f7a1d95e08"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# The vocabulary as the store spoke it before this revision.
PRIOR_KEYS = (
    "flat_rate",
    "solidarity_surcharge_rate",
    "church_tax_rate_bavaria_bw",
    "church_tax_rate_other_laender",
    "advance_lump_sum_base_rate",
    "private_sale_exemption_limit",
    "other_income_exemption_limit",
    "saver_allowance_single",
    "saver_allowance_joint",
    "loss_cap_aktien",
    "loss_cap_sonstige",
    "loss_cap_termingeschaefte",
    "opening_carryforward_aktien",
    "opening_carryforward_sonstige",
    "opening_carryforward_termingeschaefte",
    "partial_exemption_aktienfonds",
    "partial_exemption_mischfonds",
    "partial_exemption_immobilienfonds",
    "partial_exemption_auslands_immobilienfonds",
    "partial_exemption_sonstige",
)

FACTOR_KEY = "advance_lump_sum_factor"
FACTOR_SOURCE = "§ 18 Abs. 1 Satz 2 InvStG"


def upgrade() -> None:
    _pin_vocabulary((*PRIOR_KEYS, FACTOR_KEY))
    for year in (2024, 2025, 2026):
        op.execute(
            sa.text(
                "INSERT INTO statutory_value (year, key, value, source)"
                " VALUES (:year, :key, :value, :source) ON CONFLICT DO NOTHING"
            ).bindparams(year=year, key=FACTOR_KEY, value=Decimal("0.7"), source=FACTOR_SOURCE)
        )
    op.create_table(
        "fund_redemption_value",
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="CASCADE", name="fund_redemption_value_instrument_fk"
            ),
            primary_key=True,
        ),
        sa.Column("year", sa.Integer, primary_key=True),
        sa.Column("start_of_year_eur", sa.Numeric, nullable=False),
        sa.Column("end_of_year_eur", sa.Numeric, nullable=False),
        sa.Column("distributions_eur", sa.Numeric, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.CheckConstraint(
            "year >= 2009 AND year <= 2100", name="fund_redemption_value_year_in_regime"
        ),
        sa.CheckConstraint(
            "start_of_year_eur >= 0 AND end_of_year_eur >= 0 AND distributions_eur >= 0",
            name="fund_redemption_value_amounts_are_not_negative",
        ),
        sa.CheckConstraint("btrim(source) <> ''", name="fund_redemption_value_source_is_cited"),
    )


def downgrade() -> None:
    op.drop_table("fund_redemption_value")
    op.execute(sa.text("DELETE FROM statutory_value WHERE key = :key").bindparams(key=FACTOR_KEY))
    _pin_vocabulary(PRIOR_KEYS)


def _pin_vocabulary(keys: tuple[str, ...]) -> None:
    quoted_keys = ", ".join(f"'{key}'" for key in keys)
    op.drop_constraint("statutory_value_vocabulary", "statutory_value", type_="check")
    op.create_check_constraint(
        "statutory_value_vocabulary", "statutory_value", sa.text(f"key IN ({quoted_keys})")
    )
