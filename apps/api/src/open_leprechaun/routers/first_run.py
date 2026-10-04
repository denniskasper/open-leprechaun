from fastapi import APIRouter
from pydantic import BaseModel

from open_leprechaun.adapters import VenueAdaptersDep
from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.services import first_run
from open_leprechaun.services.first_run import Checklist, Key

router = APIRouter(tags=["first run"])


class ChecklistItemResponse(BaseModel):
    key: Key
    done: bool
    # An item the walk can finish without: it never holds `complete` back.
    optional: bool
    # What the state was read from, in a sentence.
    detail: str
    # The screen that completes the item.
    resolve_path: str


class ChecklistResponse(BaseModel):
    complete: bool
    items: list[ChecklistItemResponse]

    @classmethod
    def of(cls, checklist: Checklist) -> ChecklistResponse:
        return cls.model_validate(checklist, from_attributes=True)


@router.get(
    "/first-run-checklist",
    summary="The walk from an empty database to a first tax report, each step's"
    " state derived from what the database holds",
    response_model=ChecklistResponse,
)
def read_first_run_checklist(
    admin: AdminDep, engine: EngineDep, adapters: VenueAdaptersDep
) -> ChecklistResponse:
    return ChecklistResponse.of(first_run.checklist(engine, adapters))
