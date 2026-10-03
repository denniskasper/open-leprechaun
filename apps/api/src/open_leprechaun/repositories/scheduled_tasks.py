"""Writes and reads over scheduled tasks (ticket 42).

`scheduled_task` holds, per task key, what the Admin chose and what the last
run did. Whether a run is in flight is not a column: a run holds a Postgres
advisory lock on its own connection for as long as it lasts, so the lock goes
when the process does and a crash can never leave a task marked running —
or locked out — forever.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Engine, Row, text

# The advisory-lock namespace scheduled tasks claim within this database; the
# second key is the task's own, folded to the non-negative half so the lock
# reads back from pg_locks, whose objid is unsigned.
_LOCK_NAMESPACE = 4242
_LOCK_KEY_SQL = "(hashtext({key})::bigint & 2147483647)::int"
_LOCK_OF_KEY_SQL = _LOCK_KEY_SQL.format(key=":key")


def task_rows(engine: Engine) -> dict[str, Row]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT key, cron, enabled, counting_from, last_started_at, last_finished_at,"
                " last_outcome, last_error, last_detail FROM scheduled_task"
            )
        ).all()
    return {row.key: row for row in rows}


def running_keys(engine: Engine, keys: list[str]) -> set[str]:
    """Which of these tasks hold their run lock right now, in any process."""
    if not keys:
        return set()
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT k.key FROM unnest(CAST(:keys AS text[])) AS k(key)"
                " WHERE EXISTS (SELECT 1 FROM pg_locks l JOIN pg_database d ON d.oid = l.database"
                "  WHERE l.locktype = 'advisory' AND l.granted"
                "  AND d.datname = current_database()"
                # objsubid 2 is the two-key form — the only one a run takes.
                "  AND l.classid = :namespace AND l.objsubid = 2"
                f"  AND l.objid = {_LOCK_KEY_SQL.format(key='k.key')}::oid)"
            ),
            {"keys": keys, "namespace": _LOCK_NAMESPACE},
        ).all()
    return {row.key for row in rows}


@contextmanager
def run_lock(engine: Engine, key: str) -> Iterator[bool]:
    """Claim the task's run for as long as the block lasts. Yields False,
    having claimed nothing, when another run already holds it."""
    with engine.connect() as connection:
        claimed = connection.execute(
            text(f"SELECT pg_try_advisory_lock(:namespace, {_LOCK_OF_KEY_SQL})"),
            {"namespace": _LOCK_NAMESPACE, "key": key},
        ).scalar_one()
        connection.commit()
        if not claimed:
            yield False
            return
        try:
            yield True
        finally:
            try:
                connection.execute(
                    text(f"SELECT pg_advisory_unlock(:namespace, {_LOCK_OF_KEY_SQL})"),
                    {"namespace": _LOCK_NAMESPACE, "key": key},
                )
                connection.commit()
            except Exception:
                # A session that could not release must not return to the
                # pool still holding the lock; closing it releases.
                connection.invalidate()
                raise


def configure(engine: Engine, key: str, *, cron: str, enabled: bool, at: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scheduled_task (key, cron, enabled, counting_from)"
                " VALUES (:key, :cron, :enabled, :at)"
                " ON CONFLICT (key) DO UPDATE SET cron = excluded.cron,"
                " enabled = excluded.enabled, counting_from = excluded.counting_from"
            ),
            {"key": key, "cron": cron, "enabled": enabled, "at": at},
        )


def begin_counting(engine: Engine, keys: list[str], *, at: datetime) -> None:
    """Start these tasks' schedules counting from `at` — only where nothing
    is recorded yet; a task already seen, configured or run keeps its own."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scheduled_task (key, counting_from)"
                " SELECT key, :at FROM unnest(CAST(:keys AS text[])) AS k(key)"
                " ON CONFLICT (key) DO NOTHING"
            ),
            {"keys": keys, "at": at},
        )


def record_start(engine: Engine, key: str, at: datetime) -> None:
    """A run began: the previous run's outcome gives way, so the row never
    shows one run's start beside another's result."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scheduled_task (key, last_started_at) VALUES (:key, :at)"
                " ON CONFLICT (key) DO UPDATE SET last_started_at = excluded.last_started_at,"
                " last_finished_at = NULL, last_outcome = NULL, last_error = NULL,"
                " last_detail = NULL"
            ),
            {"key": key, "at": at},
        )


def record_finish(
    engine: Engine, key: str, *, at: datetime, error: str | None, detail: str | None
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE scheduled_task SET last_finished_at = :at, last_outcome = :outcome,"
                " last_error = :error, last_detail = :detail WHERE key = :key"
            ),
            {
                "key": key,
                "at": at,
                "outcome": "ok" if error is None else "failed",
                "error": error,
                "detail": detail,
            },
        )
