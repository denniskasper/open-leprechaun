"""statutory configuration store.

Every statutory constant the tax engines will need, as per-year data with a
cited source (ticket 09) — so a rule change is an UPDATE, never a code change,
and no later ticket hardcodes one.

`statutory_value` is one value per (year, key). The key vocabulary is pinned
by a CHECK; which keys a complete year requires is the service's knowledge
(services/statutory.py), because requiredness is a question, not a shape. Two
value CHECKs stop the two silent mistakes: a negative amount, and a rate
stored as a percentage (25 where 0.25 belongs). The year floor is 2009 — the
Abgeltungsteuer era, the earliest regime these engines implement.

The known values for 2024-2026 ride in with the migration, like the EUR
numéraire before them: every environment runs the chain, and a deployment
should compute the first deliverable (the 2026 return) without anyone
re-entering public law. The §20 Abs. 6 Satz 5/6 loss caps were abolished
retroactively for all open cases (JStG 2024, BGBl. 2024 I Nr. 387), so no
cap is carried — an absent cap means uncapped, not unknown.

`tax_election` is the single row of Admin choices that select which per-year
values apply — filing status picks the saver-allowance variant, the church-tax
election picks a rate or none. Singleton per ADR-0006's pattern, inserted here
so an engine never meets a missing election.
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "fc41e1dbaccd"
down_revision: str | None = "c8297dbd809b"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

RATE_KEYS = (
    "flat_rate",
    "solidarity_surcharge_rate",
    "church_tax_rate_bavaria_bw",
    "church_tax_rate_other_laender",
    "advance_lump_sum_base_rate",
)

EUR_KEYS = (
    "private_sale_exemption_limit",
    "other_income_exemption_limit",
    "saver_allowance_single",
    "saver_allowance_joint",
    "loss_cap_aktien",
    "loss_cap_sonstige",
    "loss_cap_termingeschaefte",
)

FILING_STATUSES = ("single", "joint")

CHURCH_TAX_ELECTIONS = ("none", "bavaria_bw", "other_laender")

# (key, value, source) — identical across 2024-2026 as the law stands.
EVERY_YEAR = (
    ("private_sale_exemption_limit", "1000", "§ 23 Abs. 3 Satz 5 EStG (Wachstumschancengesetz)"),
    ("other_income_exemption_limit", "256", "§ 22 Nr. 3 Satz 2 EStG"),
    ("saver_allowance_single", "1000", "§ 20 Abs. 9 Satz 1 EStG (JStG 2022)"),
    ("saver_allowance_joint", "2000", "§ 20 Abs. 9 Satz 2 EStG (JStG 2022)"),
    ("flat_rate", "0.25", "§ 32d Abs. 1 Satz 1 EStG"),
    ("solidarity_surcharge_rate", "0.055", "§ 4 Satz 1 SolzG 1995"),
    ("church_tax_rate_bavaria_bw", "0.08", "Kirchensteuergesetze Bayern und Baden-Württemberg"),
    ("church_tax_rate_other_laender", "0.09", "Kirchensteuergesetze der übrigen Länder"),
)

# The Basiszins is published each January for the year just begun.
BASE_RATES = (
    (2024, "0.0229", "BMF-Schreiben v. 05.01.2024 (Basiszins zum 2.1.2024)"),
    (2025, "0.0253", "BMF-Schreiben v. 10.01.2025 (Basiszins zum 2.1.2025)"),
    (2026, "0.0320", "BMF-Schreiben v. 13.01.2026 (Basiszins zum 2.1.2026)"),
)


def upgrade() -> None:
    quoted_keys = ", ".join(f"'{key}'" for key in RATE_KEYS + EUR_KEYS)
    quoted_rate_keys = ", ".join(f"'{key}'" for key in RATE_KEYS)
    op.create_table(
        "statutory_value",
        sa.Column("year", sa.Integer, primary_key=True),
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Numeric, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.CheckConstraint(f"key IN ({quoted_keys})", name="statutory_value_vocabulary"),
        sa.CheckConstraint("value >= 0", name="statutory_value_not_negative"),
        sa.CheckConstraint(
            f"key NOT IN ({quoted_rate_keys}) OR value <= 1",
            name="statutory_value_rate_is_a_fraction",
        ),
        sa.CheckConstraint("btrim(source) <> ''", name="statutory_value_cites_a_source"),
        sa.CheckConstraint("year BETWEEN 2009 AND 2100", name="statutory_value_year_in_regime"),
    )
    quoted_statuses = ", ".join(f"'{status}'" for status in FILING_STATUSES)
    quoted_elections = ", ".join(f"'{election}'" for election in CHURCH_TAX_ELECTIONS)
    op.create_table(
        "tax_election",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "singleton",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
            unique=True,
        ),
        sa.Column("filing_status", sa.Text, nullable=False, server_default="single"),
        sa.Column("church_tax", sa.Text, nullable=False, server_default="none"),
        sa.CheckConstraint("singleton", name="tax_election_is_singular"),
        sa.CheckConstraint(
            f"filing_status IN ({quoted_statuses})", name="tax_election_filing_status_vocabulary"
        ),
        sa.CheckConstraint(
            f"church_tax IN ({quoted_elections})", name="tax_election_church_tax_vocabulary"
        ),
    )
    op.execute("INSERT INTO tax_election DEFAULT VALUES")
    for year in (2024, 2025, 2026):
        for key, value, source in EVERY_YEAR:
            _carry(year, key, value, source)
    for year, value, source in BASE_RATES:
        _carry(year, "advance_lump_sum_base_rate", value, source)


def _carry(year: int, key: str, value: str, source: str) -> None:
    op.execute(
        sa.text(
            "INSERT INTO statutory_value (year, key, value, source)"
            " VALUES (:year, :key, :value, :source) ON CONFLICT DO NOTHING"
        ).bindparams(year=year, key=key, value=Decimal(value), source=source)
    )


def downgrade() -> None:
    op.drop_table("tax_election")
    op.drop_table("statutory_value")
