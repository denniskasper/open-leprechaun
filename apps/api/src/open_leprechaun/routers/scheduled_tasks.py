from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, Field

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.services import scheduled_tasks
from open_leprechaun.services.cron import InvalidCronError
from open_leprechaun.services.scheduled_tasks import TaskState
from open_leprechaun.tasks import ScheduledTasksDep

router = APIRouter(tags=["scheduled tasks"])


class ScheduledTaskResponse(BaseModel):
    key: str
    name: str
    description: str
    cron: str
    enabled: bool
    running: bool
    last_started_at: AwareDatetime | None
    last_finished_at: AwareDatetime | None
    duration_seconds: float | None
    # A run the API did not survive reads as failed, with an error saying so.
    outcome: Literal["ok", "failed"] | None
    error: str | None
    detail: str | None
    # None while the task is disabled; in the past when a fire is overdue.
    next_due_at: AwareDatetime | None

    @classmethod
    def of(cls, state: TaskState) -> ScheduledTaskResponse:
        return cls(
            key=state.key,
            name=state.name,
            description=state.description,
            cron=state.cron,
            enabled=state.enabled,
            running=state.running,
            last_started_at=state.last_started_at,
            last_finished_at=state.last_finished_at,
            duration_seconds=state.duration_seconds,
            outcome=state.outcome,
            error=state.error,
            detail=state.detail,
            next_due_at=state.next_due_at,
        )


class ScheduleRequest(BaseModel):
    cron: str = Field(max_length=200)
    enabled: bool


@router.get(
    "/scheduled-tasks",
    summary="Every scheduled task with its schedule and what its last run did",
    response_model=list[ScheduledTaskResponse],
)
def list_scheduled_tasks(
    admin: AdminDep, engine: EngineDep, tasks: ScheduledTasksDep
) -> list[ScheduledTaskResponse]:
    return [
        ScheduledTaskResponse.of(state)
        for state in scheduled_tasks.list_tasks(engine, tasks, now=scheduled_tasks.utc_now())
    ]


@router.put(
    "/scheduled-tasks/{key}",
    summary="Set one task's cron expression and whether it runs on it",
    response_model=ScheduledTaskResponse,
)
def configure_scheduled_task(
    key: str,
    request: ScheduleRequest,
    admin: AdminDep,
    engine: EngineDep,
    tasks: ScheduledTasksDep,
) -> ScheduledTaskResponse:
    try:
        state = scheduled_tasks.configure(
            engine,
            tasks,
            key,
            cron_expression=request.cron,
            enabled=request.enabled,
            now=scheduled_tasks.utc_now(),
        )
    except InvalidCronError as invalid:
        raise HTTPException(status_code=422, detail=str(invalid)) from invalid
    if state is None:
        raise HTTPException(status_code=404, detail="No such scheduled task.")
    return ScheduledTaskResponse.of(state)


@router.post(
    "/scheduled-tasks/{key}/run",
    summary="Run one task now and answer what the run did",
    response_model=ScheduledTaskResponse,
)
def run_scheduled_task(
    key: str, admin: AdminDep, engine: EngineDep, tasks: ScheduledTasksDep
) -> ScheduledTaskResponse:
    try:
        state = scheduled_tasks.run_now(engine, tasks, key)
    except scheduled_tasks.AlreadyRunningError as running:
        raise HTTPException(status_code=409, detail=str(running)) from running
    if state is None:
        raise HTTPException(status_code=404, detail="No such scheduled task.")
    return ScheduledTaskResponse.of(state)
