"""scheduled tasks.

What the Admin decided about a scheduled task and what its last run did
(ticket 42). The tasks themselves are declared in code; a row appears when a
scheduler first sees a task, the Admin configures it or it runs, so a task
added later needs no migration and a default schedule changed in code reaches
every instance that never chose its own.

`cron` and `enabled` are the Admin's choice — NULL until they make one, where
the task's declared default speaks. `counting_from` is where the schedule
counts forward from: when a scheduler first saw the task, then whenever the
Admin last chose — so enabling a long-idle task waits for its next due time
instead of firing for every one it missed, and a restart never begins the
wait afresh.

The `last_*` columns are the most recent run and nothing older. A run stamps
`last_started_at` and clears the rest when it begins, then states its outcome
when it ends — so a row started but never finished is a run the process did
not survive, which the schema keeps tellable from a run still in flight only
together with the advisory lock that run holds.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6b1d4e8a2c7"
down_revision: str | None = "e4c7b9a2d1f3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_task",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("cron", sa.Text),
        sa.Column("enabled", sa.Boolean),
        sa.Column("counting_from", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_outcome", sa.Text),
        sa.Column("last_error", sa.Text),
        sa.Column("last_detail", sa.Text),
        sa.CheckConstraint("last_outcome IN ('ok', 'failed')", name="scheduled_task_outcome_known"),
        # An outcome is stated exactly when the run finished, and a failure
        # always says what failed — a failed run with nothing to read would
        # send the Admin to the logs.
        sa.CheckConstraint(
            "(last_outcome IS NULL) = (last_finished_at IS NULL)",
            name="scheduled_task_outcome_with_finish",
        ),
        sa.CheckConstraint(
            "(last_outcome IS NOT DISTINCT FROM 'failed') = (last_error IS NOT NULL)",
            name="scheduled_task_failure_says_why",
        ),
        sa.CheckConstraint(
            "last_finished_at IS NULL OR last_started_at IS NOT NULL",
            name="scheduled_task_finish_after_start",
        ),
    )


def downgrade() -> None:
    op.drop_table("scheduled_task")
