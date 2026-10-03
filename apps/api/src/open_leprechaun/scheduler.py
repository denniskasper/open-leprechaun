"""The loop that answers scheduled tasks when they fall due (ticket 42).

One daemon thread per process wakes on an interval, asks which enabled tasks'
schedules have fired, and hands each to a thread of its own — so a slow sync
never delays a price update. The loop decides nothing itself: what is due,
the one-run-at-a-time rule and the recorded outcome are all
services/scheduled_tasks, the same code a manual run-now goes through. A
second process running this loop is therefore harmless — the run lock lets
exactly one of them answer each fire. A fire that falls due while its task is
still running is refused, stays owed, and is answered once the run has ended.

The loop survives whatever a tick throws. A database that is briefly away
costs the ticks it was away for, and the fires missed are answered once when
it returns.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy import Engine

from open_leprechaun.services import scheduled_tasks
from open_leprechaun.services.scheduled_tasks import Clock, Task, utc_now

# Cron's finest grain is a minute; waking twice within one keeps a fire from
# being answered more than half a minute late.
TICK_SECONDS = 30.0

_log = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        engine: Callable[[], Engine],
        tasks: Callable[[], Sequence[Task]],
        *,
        clock: Clock = utc_now,
        tick_seconds: float = TICK_SECONDS,
    ) -> None:
        # Engine and tasks arrive as factories, read on every tick: building
        # either may fail (configuration, a database not yet up) and must cost
        # a tick, not the loop.
        self._engine = engine
        self._tasks = tasks
        self._clock = clock
        self._tick_seconds = tick_seconds
        self._since = clock()
        self._stopping = threading.Event()
        self._loop: threading.Thread | None = None

    def start(self) -> None:
        self._since = self._clock()
        self._stopping.clear()
        self._loop = threading.Thread(target=self._run, name="scheduler", daemon=True)
        self._loop.start()

    def stop(self) -> None:
        """Stop answering fires. Runs in flight are left to finish or to die
        with the process — either way their lock goes with them."""
        self._stopping.set()
        if self._loop is not None:
            self._loop.join(timeout=self._tick_seconds)

    def tick(self) -> list[threading.Thread]:
        """Start a run for every task that is due now; answers the threads
        running them."""
        engine = self._engine()
        now = self._clock()
        runs = []
        for task in scheduled_tasks.due_tasks(engine, self._tasks(), now=now, since=self._since):
            run = threading.Thread(
                target=self._answer,
                args=(engine, task, now),
                name=f"scheduled-task-{task.key}",
                daemon=True,
            )
            run.start()
            runs.append(run)
        return runs

    def _answer(self, engine: Engine, task: Task, now: datetime) -> None:
        scheduled_tasks.run_if_due(engine, task, now=now, since=self._since, clock=self._clock)

    def _run(self) -> None:
        while not self._stopping.wait(self._tick_seconds):
            try:
                self.tick()
            except Exception:
                # Nothing to do with a bad tick but say so and try the next
                # one: the loop outliving it keeps every later fire answered.
                _log.exception("A scheduler tick failed; trying again next tick.")
