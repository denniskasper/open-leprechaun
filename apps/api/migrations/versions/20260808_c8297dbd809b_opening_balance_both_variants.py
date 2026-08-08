"""opening balance both variants.

A position that predates available history can be recorded honestly: the
transaction vocabulary gains `opening_balance`, which behaves like an inbound
transfer but declares that its record is reconstructed rather than observed —
so the assumption can never look identical to a real movement in a report.

Two declarations ride on the transaction header, present exactly when the
type is `opening_balance` and refused everywhere else:

- `reconstructed` names the variant, because the difference decides a tax
  outcome. `basis` means the acquisition date is known and used as given —
  for a long-held position the date is load-bearing (Haltefrist exemption)
  while the basis is cosmetic. `basis_and_date` means both are reconstructed,
  and the honest instant is the start of known history: conservatively late,
  making disposals short-term rather than assuming an older, exempt
  acquisition.
- `estimated_basis_eur` is the declared estimate of the position's total cost
  basis in the numéraire, exact fixed-point NUMERIC like every monetary value
  in this schema. Zero is a legitimate estimate; a negative one is not.

Which legs an Opening Balance carries (one in-leg, nothing else) is the
service's decision, and its tax consequence — a lot minted marked estimated,
every disposal consuming it flagged — is documented in
services/tax_treatment.py, which the tax engines alone will read.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8297dbd809b"
down_revision: str | None = "2b99560def98"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

RECONSTRUCTED = ("basis", "basis_and_date")

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
    "opening_balance",
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
    quoted_variants = ", ".join(f"'{name}'" for name in RECONSTRUCTED)
    op.add_column("transaction", sa.Column("reconstructed", sa.Text))
    op.add_column("transaction", sa.Column("estimated_basis_eur", sa.Numeric))
    op.create_check_constraint(
        "transaction_reconstructed_vocabulary",
        "transaction",
        f"reconstructed IS NULL OR reconstructed IN ({quoted_variants})",
    )
    # The declarations ARE the type: an Opening Balance always names what is
    # reconstructed and always carries its estimate; nothing else ever does.
    op.create_check_constraint(
        "transaction_opening_balance_names_reconstructed",
        "transaction",
        "(type = 'opening_balance') = (reconstructed IS NOT NULL)",
    )
    op.create_check_constraint(
        "transaction_opening_balance_carries_estimate",
        "transaction",
        "(type = 'opening_balance') = (estimated_basis_eur IS NOT NULL)",
    )
    op.create_check_constraint(
        "transaction_estimated_basis_not_negative",
        "transaction",
        "estimated_basis_eur >= 0",
    )
    _pin_transaction_types(TRANSACTION_TYPES)


def downgrade() -> None:
    # An Opening Balance returns to the unclassified inbound transfer it
    # behaves like; the declaration that its record was reconstructed has no
    # home in the earlier schema and is lost with the columns. Columns first —
    # their CHECKs go with them — so the retype never trips the tie between
    # type and declaration, and the narrower vocabulary is pinned last, once
    # no row still wears the departing type.
    op.drop_column("transaction", "estimated_basis_eur")
    op.drop_column("transaction", "reconstructed")
    op.execute("UPDATE transaction SET type = 'transfer_in' WHERE type = 'opening_balance'")
    _pin_transaction_types(tuple(name for name in TRANSACTION_TYPES if name != "opening_balance"))
