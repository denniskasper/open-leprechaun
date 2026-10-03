"""Scheduled tasks (ticket 42): work the application repeats on a schedule
the Admin controls, each run recorded where the Admin can read it.

A task is declared in code — a key, what it is called, its default schedule
and the work itself. What the Admin chose (a cron expression, enabled or not)
and what the last run did live in the database beside it. Nothing here knows
what any task does: the catalogue (services/task_catalogue) hands over the
work, and everything after that is generic.

One run of a task at a time, across every process: a run claims the task's
advisory lock before it starts and holds it until it ends. A second run —
manual or scheduled — finds the lock taken and is refused rather than queued,
so a slow task can never pile up behind itself. A fire that came due during a
run is still owed afterwards, and is answered once however many were missed.

Every run states how it ended. Work that fails says so in a sentence the
Admin reads on the settings screen, not in a log; a run the process did not
survive — started, never finished, no lock held — reads as failed too,
because "still running" would be a lie nobody could see through.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Engine, Row

from open_leprechaun.repositories import scheduled_tasks as repository
from open_leprechaun.services import cron

Clock = Callable[[], datetime]

INTERRUPTED = "The run was interrupted before it finished — the API stopped while it was running."


class TaskFailedError(Exception):
    """The work did not succeed; the message is the sentence the Admin reads
    and must be free of secret material."""


class AlreadyRunningError(Exception):
    """Another run of the same task is in flight."""


@dataclass(frozen=True)
class Task:
    """One piece of repeatable work. `run` does it and answers a one-line
    summary of what happened, or raises TaskFailedError saying what failed."""

    key: str
    name: str
    description: str
    default_cron: str
    run: Callable[[], str]
    default_enabled: bool = True


@dataclass(frozen=True)
class TaskState:
    """A task as the Admin sees it: its schedule, and its last run."""

    key: str
    name: str
    description: str
    cron: str
    enabled: bool
    running: bool
    last_started_at: datetime | None
    last_finished_at: datetime | None
    outcome: Literal["ok", "failed"] | None
    error: str | None
    detail: str | None
    # When the schedule next fires — None while the task is disabled; in the
    # past when a fire is still waiting for the scheduler to answer it.
    next_due_at: datetime | None

    @property
    def duration_seconds(self) -> float | None:
        if self.last_started_at is None or self.last_finished_at is None:
            return None
        return (self.last_finished_at - self.last_started_at).total_seconds()


def utc_now() -> datetime:
    return datetime.now(UTC)


def list_tasks(engine: Engine, tasks: Sequence[Task], *, now: datetime) -> list[TaskState]:
    rows, running = _rows_and_running(engine, [task.key for task in tasks])
    return [
        _state(task, rows.get(task.key), running=task.key in running, now=now) for task in tasks
    ]


def configure(
    engine: Engine,
    tasks: Sequence[Task],
    key: str,
    *,
    cron_expression: str,
    enabled: bool,
    now: datetime,
) -> TaskState | None:
    """Set a task's schedule and whether it runs on it. The schedule counts
    forward from this moment. None when no such task is declared; raises
    cron.InvalidCronError when the expression names no schedule."""
    task = _named(tasks, key)
    if task is None:
        return None
    cron_expression = " ".join(cron_expression.split())
    cron.validate(cron_expression)
    repository.configure(engine, key, cron=cron_expression, enabled=enabled, at=now)
    return _current(engine, task, now=now)


def run_now(
    engine: Engine, tasks: Sequence[Task], key: str, *, clock: Clock = utc_now
) -> TaskState | None:
    """Run a task this instant, whatever its schedule says and whether or not
    it is enabled. None when no such task is declared; raises
    AlreadyRunningError when a run is already in flight."""
    task = _named(tasks, key)
    if task is None:
        return None
    with repository.run_lock(engine, key) as claimed:
        if not claimed:
            raise AlreadyRunningError(f"{task.name} is already running.")
        _run(engine, task, clock)
    return _current(engine, task, now=clock())


def due_tasks(
    engine: Engine, tasks: Sequence[Task], *, now: datetime, since: datetime
) -> list[Task]:
    """The enabled tasks whose schedule has fired and not yet been answered
    by a run. `since` is when the asking scheduler began watching: a task
    nothing is recorded about yet starts counting from there, and that start
    is written down — a process restarted more often than a task's interval
    would otherwise begin the wait afresh each time and never reach a fire."""
    rows = repository.task_rows(engine)
    unseen = [task.key for task in tasks if task.key not in rows]
    if unseen:
        repository.begin_counting(engine, unseen, at=since)
        rows = repository.task_rows(engine)
    return [task for task in tasks if _is_due(task, rows.get(task.key), now=now, since=since)]


def run_if_due(
    engine: Engine, task: Task, *, now: datetime, since: datetime, clock: Clock = utc_now
) -> bool:
    """Run the task if its schedule has fired — decided under the run lock,
    so two schedulers that both saw it due answer the fire once. False when
    another run holds the task or it turned out not to be due."""
    with repository.run_lock(engine, task.key) as claimed:
        if not claimed:
            return False
        if not _is_due(task, repository.task_rows(engine).get(task.key), now=now, since=since):
            return False
        _run(engine, task, clock)
    return True


def _run(engine: Engine, task: Task, clock: Clock) -> None:
    repository.record_start(engine, task.key, clock())
    error = detail = None
    try:
        detail = task.run()
    except TaskFailedError as failed:
        error = str(failed)
    except Exception as failed:
        # A bug's message promises nothing about what it carries (ADR-0003);
        # only its type names the failure.
        error = (
            f"The task failed unexpectedly ({type(failed).__name__}); the"
            " message is withheld in case it carries secret material."
        )
    repository.record_finish(engine, task.key, at=clock(), error=error, detail=detail)


def _named(tasks: Sequence[Task], key: str) -> Task | None:
    return next((task for task in tasks if task.key == key), None)


def _current(engine: Engine, task: Task, *, now: datetime) -> TaskState:
    rows, running = _rows_and_running(engine, [task.key])
    return _state(task, rows.get(task.key), running=task.key in running, now=now)


def _rows_and_running(engine: Engine, keys: list[str]) -> tuple[dict[str, Row], set[str]]:
    """The recorded rows and which tasks hold their run lock. The two are
    separate reads, so a run starting or ending between them can look like
    one the process did not survive — started, unfinished, unlocked. Anything
    that looks so is read once more: by then a run that was merely ending has
    stated its outcome, and one merely starting holds its lock."""
    rows = repository.task_rows(engine)
    running = repository.running_keys(engine, keys)
    if any(_unfinished(rows.get(key)) and key not in running for key in keys):
        rows = repository.task_rows(engine)
        running = repository.running_keys(engine, keys)
    return rows, running


def _unfinished(row: Row | None) -> bool:
    return row is not None and row.last_started_at is not None and row.last_finished_at is None


def _schedule(task: Task, row: Row | None) -> tuple[str, bool]:
    """The Admin's choice where they made one, the declared default until."""
    if row is None or row.cron is None:
        return task.default_cron, task.default_enabled
    return row.cron, row.enabled


def _next_due(task: Task, row: Row | None, *, since: datetime) -> datetime | None:
    expression, enabled = _schedule(task, row)
    if not enabled:
        return None
    # The schedule counts forward from the latest of the last run and the
    # moment counting began — when the schedule was last chosen, or when a
    # scheduler first saw the task: a run answers every fire before it, and
    # a schedule owes nothing for the time before it existed.
    marks = [mark for mark in (row.last_started_at, row.counting_from) if mark] if row else []
    return cron.next_fire(expression, max(marks) if marks else since)


def _is_due(task: Task, row: Row | None, *, now: datetime, since: datetime) -> bool:
    due_at = _next_due(task, row, since=since)
    return due_at is not None and due_at <= now


def _state(task: Task, row: Row | None, *, running: bool, now: datetime) -> TaskState:
    expression, enabled = _schedule(task, row)
    started = row.last_started_at if row else None
    finished = row.last_finished_at if row else None
    outcome = row.last_outcome if row else None
    error = row.last_error if row else None
    if _unfinished(row) and not running:
        outcome, error = "failed", INTERRUPTED
    return TaskState(
        key=task.key,
        name=task.name,
        description=task.description,
        cron=expression,
        enabled=enabled,
        running=running,
        last_started_at=started,
        last_finished_at=finished,
        outcome=outcome,
        error=error,
        detail=row.last_detail if row else None,
        next_due_at=_next_due(task, row, since=now),
    )
