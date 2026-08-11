"""fund classification and the review flag.

A fund's taxation depends on its Teilfreistellung category (§20 InvStG), so
each fund Instrument records that category with the source of the value —
provider prefill or the Admin's own hand — and its distribution policy
(ticket 44). Nothing here states a rate: the category is the fund's fact,
the per-category rate the statutory store's.

An unknown identifier arriving by import auto-creates its Instrument rather
than dropping the row, flagged `needs_review`. Only while flagged may a
security stand with type `unknown` — resolving the review chooses a real
type, and the schema refuses to clear the flag without one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5b7d3a91c42"
down_revision: str | None = "f2a94c8e51d7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

ORIGINAL_TYPES = (
    "(family = 'crypto' AND type IN ('native', 'token'))"
    " OR (family = 'security' AND type IN ('share', 'etf', 'fund', 'bond', 'certificate'))"
    " OR (family = 'cash' AND type = 'fiat')"
)


def upgrade() -> None:
    op.add_column("instrument", sa.Column("fund_category", sa.Text))
    op.add_column("instrument", sa.Column("fund_category_source", sa.Text))
    op.add_column("instrument", sa.Column("distribution_policy", sa.Text))
    op.add_column(
        "instrument",
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    # A security auto-created for an unknown identifier may stand with type
    # 'unknown' — but only while it awaits review, so clearing the flag
    # without choosing a real type is refused by the schema.
    op.drop_constraint("instrument_type_refines_family", "instrument", type_="check")
    op.create_check_constraint(
        "instrument_type_refines_family",
        "instrument",
        "(family = 'crypto' AND type IN ('native', 'token'))"
        " OR (family = 'security'"
        " AND type IN ('share', 'etf', 'fund', 'bond', 'certificate', 'unknown'))"
        " OR (family = 'cash' AND type = 'fiat')",
    )
    op.create_check_constraint(
        "instrument_unknown_type_awaits_review",
        "instrument",
        "type <> 'unknown' OR needs_review",
    )
    # The Teilfreistellung categories of §20 InvStG, and where the value came
    # from — always the two together, so a shown category can always name its
    # source. The distribution policy travels with them but stands alone: a
    # provider may know Thesaurierend/Ausschüttend without the tax category.
    op.create_check_constraint(
        "instrument_fund_categories",
        "instrument",
        "fund_category IN"
        " ('aktienfonds', 'mischfonds', 'immobilienfonds', 'auslands_immobilienfonds',"
        " 'sonstige')",
    )
    op.create_check_constraint(
        "instrument_fund_category_sources",
        "instrument",
        "fund_category_source IN ('provider', 'admin')",
    )
    op.create_check_constraint(
        "instrument_category_names_its_source",
        "instrument",
        "(fund_category IS NULL) = (fund_category_source IS NULL)",
    )
    op.create_check_constraint(
        "instrument_distribution_policies",
        "instrument",
        "distribution_policy IN ('distributing', 'accumulating')",
    )
    op.create_check_constraint(
        "instrument_classification_only_on_funds",
        "instrument",
        "(fund_category IS NULL AND distribution_policy IS NULL)"
        " OR (family = 'security' AND type IN ('etf', 'fund'))",
    )


def downgrade() -> None:
    for name in (
        "instrument_classification_only_on_funds",
        "instrument_distribution_policies",
        "instrument_category_names_its_source",
        "instrument_fund_category_sources",
        "instrument_fund_categories",
        "instrument_unknown_type_awaits_review",
    ):
        op.drop_constraint(name, "instrument", type_="check")
    op.drop_constraint("instrument_type_refines_family", "instrument", type_="check")
    op.create_check_constraint("instrument_type_refines_family", "instrument", ORIGINAL_TYPES)
    op.drop_column("instrument", "needs_review")
    op.drop_column("instrument", "distribution_policy")
    op.drop_column("instrument", "fund_category")
    op.drop_column("instrument", "fund_category_source")
