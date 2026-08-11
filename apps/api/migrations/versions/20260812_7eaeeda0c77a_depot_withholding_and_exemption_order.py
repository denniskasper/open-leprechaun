"""depot withholding and exemption order.

A brokerage Account is a Depot, and its tax semantics are its broker's:
whether income arrives already taxed at source, and how much of the saver's
allowance an exemption order (Freistellungsauftrag) lets through untaxed
before withholding begins. Both are facts about the institution, so they
live on the Platform — withholding restricted to brokers, because no other
kind carries the behaviour — with a nullable per-Account override for a
brand that operates through several entities of different tax status.

The exemption order may only stand on a Platform that withholds at source:
lodged anywhere else it would be an answer to no question. Absent means
none. A Depot also records its base currency; like `chain` on a crypto
Account, it is metadata the schema shapes but does not require, because
Depot is vocabulary rather than a subtype and nothing branches on it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7eaeeda0c77a"
down_revision: str | None = "e5b7d3a91c42"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("platform", sa.Column("withholding", sa.Text))
    op.add_column("platform", sa.Column("exemption_order_eur", sa.Numeric))
    op.create_check_constraint(
        "platform_withholding_behaviours",
        "platform",
        "withholding IN ('at_source', 'none')",
    )
    op.create_check_constraint(
        "platform_withholding_only_on_brokers",
        "platform",
        "withholding IS NULL OR kind = 'broker'",
    )
    op.create_check_constraint(
        "platform_exemption_order_non_negative",
        "platform",
        "exemption_order_eur >= 0",
    )
    op.create_check_constraint(
        "platform_exemption_order_only_where_withheld",
        "platform",
        # NOT DISTINCT FROM, because an unset behaviour must also refuse: a
        # bare equality against NULL would let the amount slip past the CHECK.
        "exemption_order_eur IS NULL OR withholding IS NOT DISTINCT FROM 'at_source'",
    )
    op.add_column("account", sa.Column("withholding_override", sa.Text))
    op.add_column("account", sa.Column("base_currency", sa.Text))
    op.create_check_constraint(
        "account_withholding_overrides",
        "account",
        "withholding_override IN ('at_source', 'none')",
    )
    op.create_check_constraint(
        "account_base_currency_is_a_code",
        "account",
        "base_currency ~ '^[A-Z]{3}$'",
    )


def downgrade() -> None:
    for name in ("account_base_currency_is_a_code", "account_withholding_overrides"):
        op.drop_constraint(name, "account", type_="check")
    op.drop_column("account", "base_currency")
    op.drop_column("account", "withholding_override")
    for name in (
        "platform_exemption_order_only_where_withheld",
        "platform_exemption_order_non_negative",
        "platform_withholding_only_on_brokers",
        "platform_withholding_behaviours",
    ):
        op.drop_constraint(name, "platform", type_="check")
    op.drop_column("platform", "exemption_order_eur")
    op.drop_column("platform", "withholding")
