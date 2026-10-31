"""bank withholding.

A German bank withholds at source and takes an exemption order
(Freistellungsauftrag) the same way a broker does, so withholding behaviour
— and with it the exemption order, which may only stand where income is
withheld — is allowed on `bank` Platforms as well as `broker` ones. Every
other kind still refuses both.

Only the constraint widens: no Platform's data changes, since every row
that satisfied the narrower check satisfies this one. The way down narrows
it again, and so refuses while any bank still states a behaviour.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3d9e6a1f428"
down_revision: str | None = "a4e9c2f7b815"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("platform_withholding_only_on_brokers", "platform", type_="check")
    op.create_check_constraint(
        "platform_withholding_only_on_brokers_and_banks",
        "platform",
        "withholding IS NULL OR kind IN ('broker', 'bank')",
    )


def downgrade() -> None:
    op.drop_constraint("platform_withholding_only_on_brokers_and_banks", "platform", type_="check")
    op.create_check_constraint(
        "platform_withholding_only_on_brokers",
        "platform",
        "withholding IS NULL OR kind = 'broker'",
    )
