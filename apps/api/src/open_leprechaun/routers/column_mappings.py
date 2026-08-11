"""The column-mapping flow over HTTP (ticket 33): the live interpretation
the mapping screen renders while the Admin assigns columns, the saved
mappings a later file reuses, and the preview and commit of a mapped file —
the same framework endpoints' shapes as any connector import."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.ports.column_mapping import ColumnMapping, InterpretedRow, interpret
from open_leprechaun.repositories.imports import Refusal
from open_leprechaun.routers.imports import CommittedResponse, Label, PreviewResponse
from open_leprechaun.services import column_mappings
from open_leprechaun.services.column_mappings import (
    CommitRefused,
    FileRefused,
    MappingIncomplete,
)

router = APIRouter(tags=["column-mappings"])

# The name a mapping is saved under, in the Admin's words.
MappingName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MappingPayload(BaseModel):
    """One file shape as the Admin declares it — every field optional, so the
    mapping screen can interpret a half-built mapping live; what a complete
    one still lacks is the port's judgement, not the request schema's."""

    occurred_at: str | None = None
    datetime_format: str | None = None
    timezone: str | None = None
    quantity: str | None = None
    symbol: str | None = None
    fixed_symbol: str | None = None
    type: str | None = None
    fixed_type: str | None = None
    type_values: dict[str, str] = Field(default_factory=dict)
    external_id: str | None = None
    fee_quantity: str | None = None
    note: str | None = None
    delimiter: str = ","
    decimal_comma: bool = False

    def as_mapping(self) -> ColumnMapping:
        return ColumnMapping(**self.model_dump())


class InterpretRequest(BaseModel):
    # The file itself, as the text it is — same seam as the connector import.
    content: str
    mapping: MappingPayload


class InterpretedRowResponse(BaseModel):
    """One row as the import would read it: quantities as fixed-point
    strings, the timestamp already in UTC, and each unreadable cell named."""

    number: int
    external_id: str | None
    occurred_at: datetime | None
    type: str | None
    symbol: str | None
    quantity: str | None
    fee_quantity: str | None
    note: str | None
    left_out: str | None
    problems: list[str]

    @classmethod
    def of(cls, row: InterpretedRow) -> InterpretedRowResponse:
        return cls(
            number=row.number,
            external_id=row.external_id,
            occurred_at=row.occurred_at,
            type=row.type,
            symbol=row.symbol,
            quantity=None if row.quantity is None else str(row.quantity),
            fee_quantity=None if row.fee_quantity is None else str(row.fee_quantity),
            note=row.note,
            left_out=row.left_out,
            problems=list(row.problems),
        )


class InterpretationResponse(BaseModel):
    columns: list[str]
    rows: list[InterpretedRowResponse]
    row_count: int
    defects: list[str]
    # Every distinct value the mapped type column carries, over the whole
    # file — the translation rows the screen offers.
    type_values_seen: list[str]


@router.post(
    "/column-mappings/interpret",
    summary="The first rows of this file as the mapping would interpret them",
    response_model=InterpretationResponse,
)
def interpret_file(request: InterpretRequest, admin: AdminDep) -> InterpretationResponse:
    interpretation = interpret(request.content, request.mapping.as_mapping())
    return InterpretationResponse(
        columns=list(interpretation.columns),
        rows=[InterpretedRowResponse.of(row) for row in interpretation.rows],
        row_count=interpretation.row_count,
        defects=list(interpretation.defects),
        type_values_seen=list(interpretation.type_values_seen),
    )


class SaveMappingRequest(BaseModel):
    name: MappingName
    mapping: MappingPayload


class SavedMappingResponse(BaseModel):
    id: int
    name: str
    mapping: MappingPayload
    created_at: datetime


@router.get(
    "/column-mappings",
    summary="Every saved column mapping, ready to reuse against a later file",
    response_model=list[SavedMappingResponse],
)
def list_mappings(admin: AdminDep, engine: EngineDep) -> list[SavedMappingResponse]:
    return [
        SavedMappingResponse(
            id=row.id,
            name=row.name,
            mapping=MappingPayload(**row.definition),
            created_at=row.created_at,
        )
        for row in column_mappings.list_mappings(engine)
    ]


@router.post(
    "/column-mappings",
    summary="Save this mapping under a name — saving the name again replaces it",
    status_code=201,
    response_model=SavedMappingResponse,
)
def save_mapping(
    request: SaveMappingRequest, admin: AdminDep, engine: EngineDep
) -> SavedMappingResponse:
    saved = column_mappings.save(engine, name=request.name, mapping=request.mapping.as_mapping())
    if isinstance(saved, MappingIncomplete):
        raise HTTPException(status_code=422, detail=" ".join(saved.sentences))
    return SavedMappingResponse(
        id=saved.id,
        name=saved.name,
        mapping=MappingPayload(**saved.definition),
        created_at=saved.created_at,
    )


@router.delete(
    "/column-mappings/{mapping_id}",
    summary="Forget this saved mapping — imported rows keep their history",
    status_code=204,
)
def delete_mapping(mapping_id: int, admin: AdminDep, engine: EngineDep) -> None:
    if not column_mappings.delete(engine, mapping_id):
        raise HTTPException(status_code=404, detail="No such saved mapping.")


class PreviewMappedRequest(BaseModel):
    account_id: int
    content: str
    mapping: MappingPayload


@router.post(
    "/mapped-imports/preview",
    summary="What importing this file under this mapping would create, without writing anything",
    response_model=PreviewResponse,
)
def preview_mapped(
    request: PreviewMappedRequest, admin: AdminDep, engine: EngineDep
) -> PreviewResponse:
    previewed = column_mappings.preview(
        engine,
        account_id=request.account_id,
        content=request.content,
        mapping=request.mapping.as_mapping(),
    )
    if isinstance(previewed, FileRefused):
        raise HTTPException(status_code=422, detail=previewed.sentence)
    if previewed.refusal is not None and previewed.refusal.kind is Refusal.no_such_account:
        raise HTTPException(status_code=404, detail=previewed.refusal.sentence)
    return PreviewResponse.of(previewed)


class CommitMappedRequest(PreviewMappedRequest):
    label: Label


@router.post(
    "/mapped-imports",
    summary="Commit this mapped file as one reversible batch",
    status_code=201,
    response_model=CommittedResponse,
)
def commit_mapped(
    request: CommitMappedRequest, admin: AdminDep, engine: EngineDep
) -> CommittedResponse:
    committed = column_mappings.commit(
        engine,
        account_id=request.account_id,
        content=request.content,
        mapping=request.mapping.as_mapping(),
        label=request.label,
    )
    if isinstance(committed, FileRefused):
        raise HTTPException(status_code=422, detail=committed.sentence)
    if isinstance(committed, CommitRefused):
        status = 404 if committed.kind is Refusal.no_such_account else 409
        raise HTTPException(status_code=status, detail=committed.sentence)
    return CommittedResponse(
        batch_id=committed.batch_id,
        created=committed.created,
        duplicates=committed.duplicates,
        skipped=committed.skipped,
        instruments_created=committed.instruments_created,
    )
