"""provider status.

What asking each data provider last came to (ticket 55): one row per provider
name, appearing when something first asks it — the providers themselves are
declared in code, so one added later needs no migration.

`last_success_at` and the `last_error*` columns are history: the most recent
call that answered and the most recent that did not, each kept when the other
kind of call follows. `condition` is the present: what the provider's latest
call failed with — a rate limit or an outage, never conflated (ADR-0018) —
and NULL once a call answers again.

`provider_affected_instrument` names the Instruments the latest price refresh
left without a fresh price while the provider was failing — the refresh's own
finding, stored because no later read could reconstruct it. Both sides
cascade: an Instrument that goes takes its mention along.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f8d2e1a947"
down_revision: str | None = "b7e2a4c9d316"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_status",
        sa.Column("provider", sa.Text, primary_key=True),
        sa.Column("last_success_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_error_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("condition", sa.Text),
        sa.CheckConstraint(
            "condition IN ('rate_limited', 'outage')", name="provider_status_condition_known"
        ),
        # An error always says what failed, and a provider is only in a
        # condition some recorded error put it in.
        sa.CheckConstraint(
            "(last_error_at IS NULL) = (last_error IS NULL)",
            name="provider_status_error_says_what",
        ),
        sa.CheckConstraint(
            "condition IS NULL OR last_error_at IS NOT NULL",
            name="provider_status_condition_from_an_error",
        ),
    )
    op.create_table(
        "provider_affected_instrument",
        sa.Column(
            "provider",
            sa.Text,
            sa.ForeignKey("provider_status.provider", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey("instrument.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("provider_affected_instrument")
    op.drop_table("provider_status")
