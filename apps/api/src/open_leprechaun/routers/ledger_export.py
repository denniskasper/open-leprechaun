from datetime import datetime

from fastapi import APIRouter, Response
from pydantic import BaseModel

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.services import ledger_export

router = APIRouter(tags=["ledger export"])


class LeftOutResponse(BaseModel):
    """A Transaction the file does not carry, with the sentence saying why."""

    transaction_id: int
    type: str
    occurred_at: datetime
    reason: str


class LedgerExportResponse(BaseModel):
    """What the file holds and what it could not: the rows it carries, and
    every Transaction left out of it."""

    format: str
    filename: str
    row_count: int
    left_out: list[LeftOutResponse]


@router.get(
    "/ledger-export",
    summary="What the ledger export carries, and what it leaves out",
    response_model=LedgerExportResponse,
)
def get_ledger_export(admin: AdminDep, engine: EngineDep) -> LedgerExportResponse:
    export = ledger_export.export(engine)
    return LedgerExportResponse(
        format=ledger_export.FORMAT,
        filename=ledger_export.FILENAME,
        row_count=len(export.rows),
        left_out=[LeftOutResponse(**vars(entry)) for entry in export.left_out],
    )


@router.get(
    f"/ledger-export/{ledger_export.FORMAT}.csv",
    summary="The ledger as a CoinTracking CSV import file",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def download_ledger_export(admin: AdminDep, engine: EngineDep) -> Response:
    return Response(
        content=ledger_export.as_csv(ledger_export.export(engine)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{ledger_export.FILENAME}"'},
    )
