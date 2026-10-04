"""File imports over HTTP (ticket 32): the connector registry as the picker
reads it, and the preview and commit of one exported file. Everything here is
generic over the registry — adding a connector changes no line of this."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints

from open_leprechaun.adapters import CsvConnectorsDep
from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.prices import PriceSourcesDep
from open_leprechaun.repositories.imports import Refusal
from open_leprechaun.routers.imports import CommittedResponse, Label, PreviewResponse
from open_leprechaun.services import csv_imports
from open_leprechaun.services.csv_imports import CommitRefused, FileRefused

router = APIRouter(tags=["csv-imports"])

# The registry key of the connector the Admin chose.
ConnectorName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ConnectorResponse(BaseModel):
    """One connector as the picker offers it: which export to produce, and
    the timezone its timestamps are read in — stated so a local-time export
    is a declared fact, never a surprise. `file_format` is the kind of file
    the export is, which decides how its content is sent."""

    connector: str
    name: str
    expects: str
    timezone: str
    file_format: Literal["csv", "xlsx"]


@router.get(
    "/csv-connectors",
    summary="Every exported file the ledger can read, with the export to produce",
    response_model=list[ConnectorResponse],
)
def list_connectors(admin: AdminDep, connectors: CsvConnectorsDep) -> list[ConnectorResponse]:
    return [
        ConnectorResponse(
            connector=connector.connector,
            name=connector.name,
            expects=connector.expects,
            timezone=connector.timezone,
            file_format=connector.file_format,
        )
        for connector in connectors.values()
    ]


class PreviewFileRequest(BaseModel):
    connector: ConnectorName
    account_id: int
    # The exported file itself, as the connector's declared file format
    # travels: a CSV as the text it is, a workbook as its bytes in base64.
    # Exports are small enough that a JSON field beats a multipart seam.
    content: str


@router.post(
    "/csv-imports/preview",
    summary="What importing this file would create, without writing anything",
    response_model=PreviewResponse,
)
def preview_file(
    request: PreviewFileRequest, admin: AdminDep, engine: EngineDep, connectors: CsvConnectorsDep
) -> PreviewResponse:
    previewed = csv_imports.preview(
        engine,
        connectors,
        connector=request.connector,
        account_id=request.account_id,
        content=request.content,
    )
    if previewed is None:
        raise HTTPException(status_code=404, detail="No connector reads this file.")
    if isinstance(previewed, FileRefused):
        raise HTTPException(status_code=422, detail=previewed.sentence)
    if previewed.refusal is not None and previewed.refusal.kind is Refusal.no_such_account:
        raise HTTPException(status_code=404, detail=previewed.refusal.sentence)
    return PreviewResponse.of(previewed)


class CommitFileRequest(PreviewFileRequest):
    label: Label


@router.post(
    "/csv-imports",
    summary="Commit this file as one reversible batch",
    status_code=201,
    response_model=CommittedResponse,
)
def commit_file(
    request: CommitFileRequest,
    admin: AdminDep,
    engine: EngineDep,
    connectors: CsvConnectorsDep,
    prices: PriceSourcesDep,
) -> CommittedResponse:
    committed = csv_imports.commit(
        engine,
        connectors,
        prices=prices,
        connector=request.connector,
        account_id=request.account_id,
        content=request.content,
        label=request.label,
    )
    if committed is None:
        raise HTTPException(status_code=404, detail="No connector reads this file.")
    if isinstance(committed, FileRefused):
        raise HTTPException(status_code=422, detail=committed.sentence)
    if isinstance(committed, CommitRefused):
        status = 404 if committed.kind is Refusal.no_such_account else 409
        raise HTTPException(status_code=status, detail=committed.sentence)
    return CommittedResponse.of(committed)
