"""partial exemption rates.

The statutory vocabulary gains one required rate per fund category (ticket
46): `partial_exemption_<category>`, the Teilfreistellung share §20 InvStG
exempts of a fund's gains and distributions. The category is the fund's own
fact (ticket 44); the rate stays per-year configuration with a cited source,
never a constant in logic — so the known 2024-2026 values ride in with the
migration exactly as the flat rate and the Freigrenzen did. A zero for the
`sonstige` category is a statement of the statute, not an absence: §20 InvStG
grants those funds no exemption.

The key vocabulary is pinned by a CHECK, so admitting the five keys means
recreating that constraint; the value CHECKs already fit — a rate is a
non-negative fraction of one.
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "b6e19f4d3a57"
down_revision: str | None = "a52ca7128cc2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# The vocabulary as the store now speaks it — the prior constraint's lists
# plus the five partial-exemption rates.
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

OPENING_CARRYFORWARD_KEYS = (
    "opening_carryforward_aktien",
    "opening_carryforward_sonstige",
    "opening_carryforward_termingeschaefte",
)

# (key, value, source) — identical across 2024-2026 as the law stands.
PARTIAL_EXEMPTION_KEYS = (
    ("partial_exemption_aktienfonds", "0.30", "§ 20 Abs. 1 Satz 1 InvStG"),
    ("partial_exemption_mischfonds", "0.15", "§ 20 Abs. 2 Satz 1 InvStG"),
    ("partial_exemption_immobilienfonds", "0.60", "§ 20 Abs. 3 Satz 1 Nr. 1 InvStG"),
    ("partial_exemption_auslands_immobilienfonds", "0.80", "§ 20 Abs. 3 Satz 1 Nr. 2 InvStG"),
    (
        "partial_exemption_sonstige",
        "0",
        "§ 20 InvStG (keine Teilfreistellung für sonstige Investmentfonds)",
    ),
)


def upgrade() -> None:
    _pin_vocabulary(
        RATE_KEYS
        + EUR_KEYS
        + OPENING_CARRYFORWARD_KEYS
        + tuple(key for key, _, _ in PARTIAL_EXEMPTION_KEYS)
    )
    for year in (2024, 2025, 2026):
        for key, value, source in PARTIAL_EXEMPTION_KEYS:
            op.execute(
                sa.text(
                    "INSERT INTO statutory_value (year, key, value, source)"
                    " VALUES (:year, :key, :value, :source) ON CONFLICT DO NOTHING"
                ).bindparams(year=year, key=key, value=Decimal(value), source=source)
            )


def downgrade() -> None:
    quoted_keys = ", ".join(f"'{key}'" for key, _, _ in PARTIAL_EXEMPTION_KEYS)
    op.execute(f"DELETE FROM statutory_value WHERE key IN ({quoted_keys})")
    _pin_vocabulary(RATE_KEYS + EUR_KEYS + OPENING_CARRYFORWARD_KEYS)


def _pin_vocabulary(keys: tuple[str, ...]) -> None:
    quoted_keys = ", ".join(f"'{key}'" for key in keys)
    op.drop_constraint("statutory_value_vocabulary", "statutory_value", type_="check")
    op.create_check_constraint(
        "statutory_value_vocabulary", "statutory_value", sa.text(f"key IN ({quoted_keys})")
    )
