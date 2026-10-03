"""Scheduled tasks (ticket 42): work that runs on a schedule the Admin
controls, each run recording what happened, no task ever overlapping itself,
and a failure readable without opening a log.

Two seams. The HTTP API over real Postgres, with the task registry swapped
for tasks the test controls through the same dependency production serves —
that proves configuring, run-now, the recorded run and the overlap refusal.
And the scheduling decision itself (which tasks are due, and running one only
if it is) at the service, with instants the test chooses — the part the
background loop calls and no request reaches.
"""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.services import scheduled_tasks
from open_leprechaun.services.scheduled_tasks import Task, TaskFailedError
from open_leprechaun.tasks import get_scheduled_tasks


class Work:
    """A task body under test control: counts its runs, and answers, fails or
    blocks as the test chooses."""

    def __init__(self, answer="3 things done."):
        self.answer = answer
        self.fails_with: Exception | None = None
        self.runs = 0
        self.started = threading.Event()
        self.release: threading.Event | None = None

    def __call__(self) -> str:
        self.runs += 1
        self.started.set()
        if self.release is not None:
            assert self.release.wait(timeout=10)
        if self.fails_with is not None:
            raise self.fails_with
        return self.answer


@pytest.fixture
def prices() -> Work:
    return Work()


@pytest.fixture
def sync() -> Work:
    return Work(answer="Nothing new.")


@pytest.fixture
def tasks(prices: Work, sync: Work) -> tuple[Task, ...]:
    return (
        Task(
            key="prices",
            name="Price update",
            description="Prices everything.",
            default_cron="*/15 * * * *",
            run=prices,
        ),
        Task(
            key="sync",
            name="Sync",
            description="Pulls everything.",
            default_cron="0 3 * * *",
            default_enabled=False,
            run=sync,
        ),
    )


@pytest.fixture
def client(db: Engine, tasks: tuple[Task, ...]) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_scheduled_tasks] = lambda: tasks
    with TestClient(app) as client:
        yield client


def listed(client: TestClient, key: str) -> dict:
    return next(task for task in client.get("/api/scheduled-tasks").json() if task["key"] == key)


def test_every_declared_task_is_listed_on_its_default_schedule_before_any_run(client):
    response = client.get("/api/scheduled-tasks")

    assert response.status_code == 200
    assert [
        (task["key"], task["name"], task["cron"], task["enabled"]) for task in response.json()
    ] == [
        ("prices", "Price update", "*/15 * * * *", True),
        ("sync", "Sync", "0 3 * * *", False),
    ]
    never_run = response.json()[0]
    assert never_run["running"] is False
    assert never_run["last_started_at"] is None
    assert never_run["duration_seconds"] is None
    assert never_run["outcome"] is None
    assert never_run["error"] is None


def test_an_enabled_task_states_when_it_is_next_due_and_a_disabled_one_does_not(client):
    assert listed(client, "prices")["next_due_at"] is not None
    assert listed(client, "sync")["next_due_at"] is None


def test_the_admin_sets_a_tasks_cron_expression_and_enables_it(client):
    response = client.put("/api/scheduled-tasks/sync", json={"cron": "30 4 * * 1", "enabled": True})

    assert response.status_code == 200
    assert (response.json()["cron"], response.json()["enabled"]) == ("30 4 * * 1", True)
    assert (listed(client, "sync")["cron"], listed(client, "sync")["enabled"]) == (
        "30 4 * * 1",
        True,
    )
    # One task's schedule is its own.
    assert (listed(client, "prices")["cron"], listed(client, "prices")["enabled"]) == (
        "*/15 * * * *",
        True,
    )


def test_a_task_is_disabled_on_its_own(client):
    client.put("/api/scheduled-tasks/prices", json={"cron": "*/15 * * * *", "enabled": False})

    assert listed(client, "prices")["enabled"] is False
    assert listed(client, "prices")["next_due_at"] is None


def test_a_cron_expression_naming_no_schedule_is_refused_in_words(client):
    response = client.put(
        "/api/scheduled-tasks/prices", json={"cron": "0 24 * * *", "enabled": True}
    )

    assert response.status_code == 422
    assert "hour" in response.json()["detail"]
    assert listed(client, "prices")["cron"] == "*/15 * * * *"


def test_configuring_or_running_an_undeclared_task_says_so(client):
    put = client.put("/api/scheduled-tasks/nope", json={"cron": "* * * * *", "enabled": True})
    post = client.post("/api/scheduled-tasks/nope/run")

    assert (put.status_code, post.status_code) == (404, 404)


def test_run_now_does_the_work_and_records_the_run(client, prices):
    response = client.post("/api/scheduled-tasks/prices/run")

    assert response.status_code == 200
    assert prices.runs == 1
    recorded = listed(client, "prices")
    assert response.json() == recorded
    assert recorded["outcome"] == "ok"
    assert recorded["detail"] == "3 things done."
    assert recorded["error"] is None
    assert recorded["running"] is False
    started = datetime.fromisoformat(recorded["last_started_at"])
    finished = datetime.fromisoformat(recorded["last_finished_at"])
    assert datetime.now(UTC) - started < timedelta(minutes=1)
    assert recorded["duration_seconds"] == pytest.approx((finished - started).total_seconds())
    assert recorded["duration_seconds"] >= 0


def test_run_now_runs_a_disabled_task_and_leaves_it_disabled(client, sync):
    response = client.post("/api/scheduled-tasks/sync/run")

    assert response.status_code == 200
    assert sync.runs == 1
    assert listed(client, "sync")["enabled"] is False


def test_a_failing_task_states_its_failure_in_the_list(client, prices):
    prices.fails_with = TaskFailedError("coingecko is not answering — 0 fresh, 2 stale.")

    response = client.post("/api/scheduled-tasks/prices/run")

    assert response.status_code == 200
    recorded = listed(client, "prices")
    assert recorded["outcome"] == "failed"
    assert recorded["error"] == "coingecko is not answering — 0 fresh, 2 stale."
    assert recorded["duration_seconds"] is not None


def test_a_crashing_task_is_recorded_failed_without_its_message(client, prices):
    prices.fails_with = RuntimeError("api_key=hunter2 rejected")

    response = client.post("/api/scheduled-tasks/prices/run")

    assert response.status_code == 200
    recorded = listed(client, "prices")
    assert recorded["outcome"] == "failed"
    assert "RuntimeError" in recorded["error"]
    assert "hunter2" not in recorded["error"]


def test_a_later_success_clears_the_recorded_failure(client, prices):
    prices.fails_with = TaskFailedError("Down.")
    client.post("/api/scheduled-tasks/prices/run")
    prices.fails_with = None

    client.post("/api/scheduled-tasks/prices/run")

    recorded = listed(client, "prices")
    assert (recorded["outcome"], recorded["error"]) == ("ok", None)


def test_a_second_run_of_a_running_task_is_refused_and_does_no_work(client, prices, sync):
    prices.release = threading.Event()
    first = threading.Thread(target=client.post, args=("/api/scheduled-tasks/prices/run",))
    first.start()
    try:
        assert prices.started.wait(timeout=10)

        overlapping = client.post("/api/scheduled-tasks/prices/run")

        assert overlapping.status_code == 409
        assert overlapping.json()["detail"] == "Price update is already running."
        assert prices.runs == 1
        in_flight = listed(client, "prices")
        assert in_flight["running"] is True
        assert in_flight["outcome"] is None
        # Another task is not held up by this one.
        assert client.post("/api/scheduled-tasks/sync/run").status_code == 200
        assert listed(client, "sync")["running"] is False
    finally:
        prices.release.set()
        first.join(timeout=10)

    assert listed(client, "prices")["running"] is False
    assert listed(client, "prices")["outcome"] == "ok"
    assert client.post("/api/scheduled-tasks/prices/run").status_code == 200
    assert prices.runs == 2


def test_a_run_the_process_did_not_survive_reads_as_failed(client, db):
    # What a killed process leaves behind: a start, no finish, no lock held.
    from open_leprechaun.repositories import scheduled_tasks as repository

    repository.record_start(db, "prices", datetime(2026, 10, 3, 9, 0, tzinfo=UTC))

    recorded = listed(client, "prices")

    assert recorded["running"] is False
    assert recorded["outcome"] == "failed"
    assert "interrupted" in recorded["error"]


# --- the scheduling decision -------------------------------------------------

WATCHING_SINCE = datetime(2026, 10, 3, 9, 7, tzinfo=UTC)


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, 3, hour, minute, second, tzinfo=UTC)


def due_keys(db, tasks, now):
    return [
        task.key for task in scheduled_tasks.due_tasks(db, tasks, now=now, since=WATCHING_SINCE)
    ]


def test_a_task_is_not_due_before_its_schedule_fires(db, tasks):
    assert due_keys(db, tasks, at(9, 14)) == []


def test_an_enabled_task_falls_due_when_its_schedule_fires_and_a_disabled_one_never(db, tasks):
    # Both schedules have fired by the next morning; only one is enabled.
    assert due_keys(db, tasks, at(9, 15)) == ["prices"]
    assert due_keys(db, tasks, at(9, 15) + timedelta(days=1)) == ["prices"]


def test_a_due_task_runs_once_and_is_then_not_due_until_the_next_fire(db, tasks, prices):
    (task, _) = tasks
    clock = iter([at(9, 15), at(9, 16)]).__next__

    ran = scheduled_tasks.run_if_due(db, task, now=at(9, 15), since=WATCHING_SINCE, clock=clock)

    assert ran is True
    assert prices.runs == 1
    assert due_keys(db, tasks, at(9, 16)) == []
    assert due_keys(db, tasks, at(9, 30)) == ["prices"]
    (state, _) = scheduled_tasks.list_tasks(db, tasks, now=at(9, 16))
    assert state.duration_seconds == 60
    assert state.next_due_at == at(9, 30)


def test_a_second_scheduler_answering_the_same_fire_does_no_work(db, tasks, prices):
    (task, _) = tasks
    scheduled_tasks.run_if_due(
        db, task, now=at(9, 15), since=WATCHING_SINCE, clock=lambda: at(9, 15)
    )

    ran_again = scheduled_tasks.run_if_due(db, task, now=at(9, 15), since=WATCHING_SINCE)

    assert ran_again is False
    assert prices.runs == 1


def test_a_scheduled_fire_during_a_run_is_skipped_not_queued(db, tasks, prices):
    (task, _) = tasks
    prices.release = threading.Event()
    running = threading.Thread(target=scheduled_tasks.run_now, args=(db, tasks, "prices"))
    running.start()
    try:
        assert prices.started.wait(timeout=10)

        ran = scheduled_tasks.run_if_due(
            db, task, now=datetime.now(UTC) + timedelta(hours=1), since=WATCHING_SINCE
        )

        assert ran is False
        assert prices.runs == 1
    finally:
        prices.release.set()
        running.join(timeout=10)


def test_a_newly_chosen_schedule_counts_forward_from_when_it_was_chosen(db, tasks):
    # Enabled long after the scheduler began watching: the fires in between
    # are not owed.
    scheduled_tasks.configure(
        db, tasks, "sync", cron_expression="0 * * * *", enabled=True, now=at(14, 20)
    )

    assert "sync" not in due_keys(db, tasks, at(14, 59))
    assert "sync" in due_keys(db, tasks, at(15, 0))


def test_a_fire_missed_while_nothing_was_watching_is_answered_once(db, tasks, prices):
    (task, _) = tasks
    scheduled_tasks.run_if_due(
        db, task, now=at(9, 15), since=WATCHING_SINCE, clock=lambda: at(9, 15)
    )
    much_later = at(9, 15) + timedelta(days=2)

    scheduled_tasks.run_if_due(db, task, now=much_later, since=much_later, clock=lambda: much_later)

    assert prices.runs == 2
    assert due_keys(db, tasks, much_later + timedelta(minutes=1)) == []


# --- the loop ----------------------------------------------------------------


def test_a_tick_runs_what_is_due_and_nothing_else(db, tasks, prices, sync):
    from open_leprechaun.scheduler import Scheduler

    instants = iter([WATCHING_SINCE] + [at(9, 15)] * 10)
    scheduler = Scheduler(lambda: db, lambda: tasks, clock=lambda: next(instants))

    for run in scheduler.tick():
        run.join(timeout=10)

    assert (prices.runs, sync.runs) == (1, 0)
    (state, _) = scheduled_tasks.list_tasks(db, tasks, now=at(9, 16))
    assert state.outcome == "ok"


def test_a_slow_task_does_not_hold_up_another_that_is_due(db, tasks, prices, sync):
    from open_leprechaun.scheduler import Scheduler

    scheduled_tasks.configure(
        db, tasks, "sync", cron_expression="*/15 * * * *", enabled=True, now=WATCHING_SINCE
    )
    prices.release = threading.Event()
    instants = iter([WATCHING_SINCE] + [at(9, 15)] * 10)
    scheduler = Scheduler(lambda: db, lambda: tasks, clock=lambda: next(instants))

    runs = scheduler.tick()
    try:
        assert prices.started.wait(timeout=10)
        assert sync.started.wait(timeout=10)
    finally:
        prices.release.set()
        for run in runs:
            run.join(timeout=10)

    assert (prices.runs, sync.runs) == (1, 1)


def test_a_restart_does_not_begin_a_never_run_tasks_wait_afresh(db, tasks):
    # A scheduler saw the task at 09:07, then the process restarted at 09:14
    # — more often than the task's interval. The 09:15 fire is still owed.
    assert due_keys(db, tasks, at(9, 8)) == []

    restarted = scheduled_tasks.due_tasks(db, tasks, now=at(9, 15), since=at(9, 14, 30))

    assert [task.key for task in restarted] == ["prices"]
