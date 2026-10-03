"""corporate actions.

An issuer event that changes a holding without a trade (ticket 52): split —
a reverse split is one whose ratio falls below one — spin-off, merger,
capital return. A row is the event itself and nothing else: the lot engine
walks it beside the ledger, so its whole effect is derived and reversing it
is removing the row (ADR-0014). `tax_lot` gains nothing — the materialisation
already declares this table as an input class, and its first row marks every
dependent materialisation stale by itself.

What each kind states, held to exactly that by the schema:

- `split`: `units_new` for every `units_old` held — quantity alone moves.
- `merger`: `units_new` of the target Instrument for every `units_old` of
  this one, the whole basis carried across.
- `spin_off`: `units_new` of the target for every `units_old` held, and the
  `basis_share` of each lot's basis that moves with them — the ratio the
  Admin supplies, never one the application asserts.
- `capital_return`: `amount_per_unit_eur` taken off the basis of each unit.

`reviewed_at` is the Admin's own mark on an event whose treatment is
fact-specific; it is prose about the event, not an input of any figure. The
Instruments are held by RESTRICT: an event is a source of truth, so the
Instrument it names cannot silently go from under it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4c7b9a2d1f3"
down_revision: str | None = "d8a2c5f61b90"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

KINDS = ("split", "spin_off", "merger", "capital_return")


def upgrade() -> None:
    quoted_kinds = ", ".join(f"'{kind}'" for kind in KINDS)
    op.create_table(
        "corporate_action",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey(
                "instrument.id", ondelete="RESTRICT", name="corporate_action_instrument_fk"
            ),
            nullable=False,
        ),
        sa.Column("effective_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("units_new", sa.Numeric),
        sa.Column("units_old", sa.Numeric),
        sa.Column(
            "target_instrument_id",
            sa.Integer,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT", name="corporate_action_target_fk"),
        ),
        sa.Column("basis_share", sa.Numeric),
        sa.Column("amount_per_unit_eur", sa.Numeric),
        sa.Column("note", sa.Text),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(f"kind IN ({quoted_kinds})", name="corporate_action_kinds"),
        # A ratio is both of its sides, positive — and a capital return, which
        # moves no quantity, carries none.
        sa.CheckConstraint(
            "(kind = 'capital_return' AND units_new IS NULL AND units_old IS NULL)"
            " OR (kind <> 'capital_return' AND units_new IS NOT NULL AND units_old IS NOT NULL"
            " AND units_new > 0 AND units_old > 0)",
            name="corporate_action_ratio_belongs_to_unit_changes",
        ),
        sa.CheckConstraint(
            "(kind IN ('spin_off', 'merger')) = (target_instrument_id IS NOT NULL)",
            name="corporate_action_target_belongs_to_spin_off_and_merger",
        ),
        sa.CheckConstraint(
            "target_instrument_id <> instrument_id", name="corporate_action_target_is_another"
        ),
        # Strictly inside the interval: a share of nothing is no spin-off and
        # a share of everything is a merger.
        sa.CheckConstraint(
            "(kind = 'spin_off' AND basis_share IS NOT NULL"
            " AND basis_share > 0 AND basis_share < 1)"
            " OR (kind <> 'spin_off' AND basis_share IS NULL)",
            name="corporate_action_basis_share_belongs_to_spin_off",
        ),
        sa.CheckConstraint(
            "(kind = 'capital_return' AND amount_per_unit_eur IS NOT NULL"
            " AND amount_per_unit_eur > 0)"
            " OR (kind <> 'capital_return' AND amount_per_unit_eur IS NULL)",
            name="corporate_action_amount_belongs_to_capital_return",
        ),
    )
    # The derivation walks every event in effect order.
    op.create_index("corporate_action_in_effect_order", "corporate_action", ["effective_at", "id"])


def downgrade() -> None:
    op.drop_table("corporate_action")
