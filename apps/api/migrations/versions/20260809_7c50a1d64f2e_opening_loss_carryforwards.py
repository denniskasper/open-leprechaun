"""opening loss carryforwards.

The statutory vocabulary gains one optional key per §20 category (ticket 27):
`opening_carryforward_<category>`, the loss carryforward a Verlustverrech-
nungstopf opens the entered year with, from a Verlustfeststellung predating
the ledger — a loss established elsewhere still shelters income here
(ADR-0013). Absent means zero, never unknown, so no year requires one and
nothing rides in with the migration: the value is the Admin's own assessment
data, never public law.

The key vocabulary is pinned by a CHECK, so admitting the three keys means
recreating that constraint; the value CHECKs already fit — an opening
carryforward is a non-negative EUR amount entered with the assessment that
established it as its source.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c50a1d64f2e"
down_revision: str | None = "b2f2722a3d33"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# The vocabulary as the store now speaks it — the prior constraint's lists
# plus the three opening carryforwards.
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


def upgrade() -> None:
    _pin_vocabulary(RATE_KEYS + EUR_KEYS + OPENING_CARRYFORWARD_KEYS)


def downgrade() -> None:
    quoted_keys = ", ".join(f"'{key}'" for key in OPENING_CARRYFORWARD_KEYS)
    op.execute(f"DELETE FROM statutory_value WHERE key IN ({quoted_keys})")
    _pin_vocabulary(RATE_KEYS + EUR_KEYS)


def _pin_vocabulary(keys: tuple[str, ...]) -> None:
    quoted_keys = ", ".join(f"'{key}'" for key in keys)
    op.drop_constraint("statutory_value_vocabulary", "statutory_value", type_="check")
    op.create_check_constraint(
        "statutory_value_vocabulary", "statutory_value", sa.text(f"key IN ({quoted_keys})")
    )
