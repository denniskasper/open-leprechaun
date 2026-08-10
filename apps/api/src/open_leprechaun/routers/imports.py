from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.repositories import imports
from open_leprechaun.repositories.imports import Refusal
from open_leprechaun.routers.transactions import LegRole, Note, Quantity, TransactionType
from open_leprechaun.services.imports import (
    CommitRefused,
    ImportLeg,
    ImportRow,
    InstrumentSpec,
    Preview,
    commit,
    evaluate,
)

router = APIRouter(tags=["imports"])

# The per-kind provenance string stamped on every imported row — one half of
# the deduplication key. Trimmed, so whitespace cannot mint a second source.
Source = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# The identifier the venue itself gave the record — the other half of the
# deduplication key, deliberately its own name so the two halves never blur.
ExternalId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# What the Admin imported, in their words — a filename, usually.
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TokenSpecPayload(BaseModel):
    kind: Literal["token"]
    symbol: str
    name: str
    chain: str
    contract_address: str
    pegged_currency: str | None = None


class NativeSpecPayload(BaseModel):
    kind: Literal["native"]
    symbol: str
    name: str
    chain: str


class SecuritySpecPayload(BaseModel):
    kind: Literal["security"]
    symbol: str
    name: str
    security_type: Literal["share", "etf", "fund", "bond", "certificate"]
    isin: str


class CashSpecPayload(BaseModel):
    kind: Literal["cash"]
    symbol: str
    name: str


InstrumentSpecPayload = Annotated[
    TokenSpecPayload | NativeSpecPayload | SecuritySpecPayload | CashSpecPayload,
    Field(discriminator="kind"),
]


class ImportLegPayload(BaseModel):
    role: LegRole
    quantity: Quantity
    # The Instrument, by id or by identity — exactly one; the evaluation
    # refuses a leg carrying both or neither with its own sentence.
    instrument_id: int | None = None
    instrument: InstrumentSpecPayload | None = None
    # A fee names the sibling leg it was charged against by position.
    charged_against: int | None = None


class ImportRowPayload(BaseModel):
    external_id: ExternalId
    type: TransactionType
    occurred_at: AwareDatetime
    note: Note = None
    legs: list[ImportLegPayload]


class ImportFileRequest(BaseModel):
    source: Source
    account_id: int
    rows: list[ImportRowPayload]


class CommitImportRequest(ImportFileRequest):
    label: Label


class ToCreateResponse(BaseModel):
    external_id: str
    type: TransactionType
    occurred_at: AwareDatetime


class SkippedResponse(BaseModel):
    external_id: str
    reason: str


class NewInstrumentResponse(BaseModel):
    kind: str
    symbol: str
    name: str


class PreviewResponse(BaseModel):
    to_create: list[ToCreateResponse]
    duplicates: int
    duplicate_external_ids: list[str]
    skipped: list[SkippedResponse]
    new_instruments: list[NewInstrumentResponse]
    warnings: list[str]

    @classmethod
    def of(cls, preview: Preview) -> PreviewResponse:
        return cls(
            to_create=[
                ToCreateResponse(
                    external_id=row.external_id, type=row.type, occurred_at=row.occurred_at
                )
                for row in preview.creatable
            ],
            duplicates=len(preview.duplicate_external_ids),
            duplicate_external_ids=list(preview.duplicate_external_ids),
            skipped=[
                SkippedResponse(external_id=skip.external_id, reason=skip.reason)
                for skip in preview.skipped
            ],
            new_instruments=[
                NewInstrumentResponse(kind=spec.kind, symbol=spec.symbol, name=spec.name)
                for spec in preview.new_instruments
            ],
            warnings=list(preview.warnings),
        )


class CommittedResponse(BaseModel):
    # None when nothing was created: a pure re-import records no batch.
    batch_id: int | None
    created: int
    duplicates: int
    skipped: int
    instruments_created: int


class BatchResponse(BaseModel):
    id: int
    source: str
    label: str
    account_id: int
    created_at: AwareDatetime
    rows: int
    overridden: int


@router.post(
    "/imports/preview",
    summary="What an import would create, without writing anything",
    response_model=PreviewResponse,
)
def preview_import(
    request: ImportFileRequest, admin: AdminDep, engine: EngineDep
) -> PreviewResponse:
    preview = evaluate(
        engine, source=request.source, account_id=request.account_id, rows=_rows(request)
    )
    if preview.refusal is not None and preview.refusal.kind is Refusal.no_such_account:
        raise HTTPException(status_code=404, detail=preview.refusal.sentence)
    return PreviewResponse.of(preview)


@router.post(
    "/imports",
    summary="Commit an import as one reversible batch",
    status_code=201,
    response_model=CommittedResponse,
)
def commit_import(
    request: CommitImportRequest, admin: AdminDep, engine: EngineDep
) -> CommittedResponse:
    committed = commit(
        engine,
        source=request.source,
        label=request.label,
        account_id=request.account_id,
        rows=_rows(request),
    )
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


@router.get(
    "/import-batches",
    summary="Every import, newest first, as the unit it can be reversed by",
    response_model=list[BatchResponse],
)
def list_batches(admin: AdminDep, engine: EngineDep) -> list[BatchResponse]:
    return [
        BatchResponse(
            id=batch.id,
            source=batch.source,
            label=batch.label,
            account_id=batch.account_id,
            created_at=batch.created_at,
            rows=batch.rows,
            overridden=batch.overridden,
        )
        for batch in imports.list_batches(engine)
    ]


@router.delete(
    "/import-batches/{batch_id}",
    summary="Reverse one import as a unit",
    status_code=204,
)
def reverse_batch(batch_id: int, admin: AdminDep, engine: EngineDep) -> None:
    """Removes what the batch created; rows the Admin edited by hand are the
    Admin's now and stand, their registry tombstones keeping a later
    re-import from resurrecting the originals."""
    if not imports.reverse_batch(engine, batch_id):
        raise HTTPException(status_code=404, detail="No such Import Batch.")


def _rows(request: ImportFileRequest) -> list[ImportRow]:
    return [
        ImportRow(
            external_id=row.external_id,
            type=row.type,
            occurred_at=row.occurred_at,
            note=row.note,
            legs=tuple(
                ImportLeg(
                    role=leg.role,
                    quantity=leg.quantity,
                    instrument_id=leg.instrument_id,
                    instrument=_spec(leg.instrument),
                    charged_against=leg.charged_against,
                )
                for leg in row.legs
            ),
        )
        for row in request.rows
    ]


def _spec(payload: InstrumentSpecPayload | None) -> InstrumentSpec | None:
    # Each payload variant carries exactly the identity fields its kind needs;
    # the spec's remaining fields keep their None defaults.
    return None if payload is None else InstrumentSpec(**payload.model_dump())
