"""Connections over HTTP: credentials go in once, and no response ever
carries secret material in any form (ADR-0003) — the request model is the
last time the API sees a key, a secret or a passphrase in the clear."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, PlainSerializer, StringConstraints

from open_leprechaun.adapters import VenueAdaptersDep
from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.ports.venues import VENUES
from open_leprechaun.prices import PriceSourcesDep
from open_leprechaun.routers.imports import PriceConditionResponse, UnpricedRowResponse
from open_leprechaun.services import connection_sync, connections, coverage, reconciliation
from open_leprechaun.services.connections import (
    ConnectionOverview,
    CredentialsUnreadableError,
    Refusal,
)
from open_leprechaun.settings import SettingsDep

router = APIRouter(tags=["connections"])

# Labels and keys arrive from a human pasting; trimmed before a stray space
# can become part of an identity or a credential.
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class VenueAdapterResponse(BaseModel):
    """One adapter kind a venue serves, with its declared capability: how far
    back the venue actually reaches (ADR-0008) — None where its history is
    unbounded."""

    kind: str
    lookback_days: int | None


class VenueResponse(BaseModel):
    venue: str
    name: str
    # UI copy: the read-only permission set to grant when minting the key.
    required_scope: str
    requires_secret: bool
    requires_passphrase: bool
    # The kinds this venue's adapters serve — what pairing is offered for;
    # empty until the venue's adapters ship.
    adapters: list[VenueAdapterResponse]


class AdapterStatusResponse(BaseModel):
    adapter_kind: str
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None


class AccountPairingResponse(BaseModel):
    adapter_kind: str
    account_id: int


class ConnectionResponse(BaseModel):
    """Everything the Admin ever sees of a Connection again: a label, a
    fingerprint, a last-used timestamp, per-kind results and per-kind Account
    pairings. Deliberately no field that could carry secret material."""

    id: int
    platform_id: int
    venue: str
    label: str
    fingerprint: str
    last_used_at: datetime | None
    statuses: list[AdapterStatusResponse]
    pairings: list[AccountPairingResponse]

    @classmethod
    def of(cls, connection: ConnectionOverview) -> ConnectionResponse:
        return cls(
            id=connection.id,
            platform_id=connection.platform_id,
            venue=connection.venue,
            label=connection.label,
            fingerprint=connection.fingerprint,
            last_used_at=connection.last_used_at,
            statuses=[
                AdapterStatusResponse(
                    adapter_kind=status.adapter_kind,
                    last_success_at=status.last_success_at,
                    last_error_at=status.last_error_at,
                    last_error=status.last_error,
                )
                for status in connection.statuses
            ],
            pairings=[
                AccountPairingResponse(
                    adapter_kind=pairing.adapter_kind, account_id=pairing.account_id
                )
                for pairing in connection.pairings
            ],
        )


class RegisterConnectionRequest(BaseModel):
    platform_id: int
    venue: str
    label: NonBlank
    key: NonBlank
    secret: str | None = None
    passphrase: str | None = None


class RegisteredResponse(BaseModel):
    id: int


@router.get(
    "/connections/venues",
    summary="Every venue a Connection may speak to, with its required read-only scope",
    response_model=list[VenueResponse],
)
def list_venues(admin: AdminDep) -> list[VenueResponse]:
    return [
        VenueResponse(
            venue=venue.venue,
            name=venue.name,
            required_scope=venue.required_scope,
            requires_secret=venue.requires_secret,
            requires_passphrase=venue.requires_passphrase,
            adapters=[
                VenueAdapterResponse(kind=adapter.kind, lookback_days=adapter.lookback_days)
                for adapter in venue.adapters
            ],
        )
        for venue in VENUES.values()
    ]


@router.get(
    "/connections",
    summary="Every Connection: label, fingerprint, last use and per-kind results",
    response_model=list[ConnectionResponse],
)
def list_connections(admin: AdminDep, engine: EngineDep) -> list[ConnectionResponse]:
    return [ConnectionResponse.of(connection) for connection in connections.overview(engine)]


class CoverageWarningResponse(BaseModel):
    """One venue account whose synced coverage begins after the earliest
    activity recorded elsewhere (ticket 40) — a silent history gap, named."""

    connection_id: int
    connection_label: str
    venue: str
    platform_name: str
    account_id: int
    account_name: str
    coverage_starts_at: datetime
    earliest_elsewhere_at: datetime

    @classmethod
    def of(cls, warning: coverage.CoverageWarning) -> CoverageWarningResponse:
        return cls(
            connection_id=warning.connection_id,
            connection_label=warning.connection_label,
            venue=warning.venue,
            platform_name=warning.platform_name,
            account_id=warning.account_id,
            account_name=warning.account_name,
            coverage_starts_at=warning.coverage_starts_at,
            earliest_elsewhere_at=warning.earliest_elsewhere_at,
        )


@router.get(
    "/connections/coverage-warnings",
    summary="Every venue whose coverage starts later than the earliest activity elsewhere",
    response_model=list[CoverageWarningResponse],
)
def coverage_warnings(admin: AdminDep, engine: EngineDep) -> list[CoverageWarningResponse]:
    return [CoverageWarningResponse.of(warning) for warning in coverage.warnings(engine)]


@router.post(
    "/connections",
    summary="Store one venue account's credentials, encrypted, never to be returned",
    status_code=201,
    response_model=RegisteredResponse,
)
def register_connection(
    request: RegisterConnectionRequest,
    admin: AdminDep,
    engine: EngineDep,
    settings: SettingsDep,
) -> RegisteredResponse:
    created = connections.register(
        engine,
        settings,
        platform_id=request.platform_id,
        venue=request.venue,
        label=request.label,
        key=request.key,
        secret=request.secret,
        passphrase=request.passphrase,
    )
    if created is Refusal.no_such_platform:
        raise HTTPException(status_code=404, detail="No such Platform.")
    if created is Refusal.label_taken:
        raise HTTPException(
            status_code=409, detail=f"{request.label!r} already exists under this Platform."
        )
    if created is Refusal.unknown_venue:
        raise HTTPException(status_code=422, detail="No adapter knows this venue.")
    if created is Refusal.secret_missing:
        raise HTTPException(status_code=422, detail="This venue signs with a secret; enter one.")
    if created is Refusal.passphrase_missing:
        raise HTTPException(status_code=422, detail="This venue requires a passphrase; enter one.")
    return RegisteredResponse(id=created)


@router.delete(
    "/connections/{connection_id}",
    summary="Remove a Connection and its credentials",
    status_code=204,
)
def remove_connection(connection_id: int, admin: AdminDep, engine: EngineDep) -> None:
    if not connections.remove(engine, connection_id):
        raise HTTPException(status_code=404, detail="No such Connection.")


class KindTestResponse(BaseModel):
    """One adapter kind's test outcome — `detail` is the venue's own success
    sentence, `error` the failure's, never both."""

    adapter_kind: str
    ok: bool
    detail: str | None
    error: str | None

    @classmethod
    def of(cls, result: connection_sync.KindTest) -> KindTestResponse:
        return cls(
            adapter_kind=result.adapter_kind,
            ok=result.error is None,
            detail=result.detail,
            error=result.error,
        )


@router.post(
    "/connections/{connection_id}/test",
    summary="Prove the credentials open every kind the venue serves, reported per kind",
    response_model=list[KindTestResponse],
)
def test_connection(
    connection_id: int,
    admin: AdminDep,
    engine: EngineDep,
    settings: SettingsDep,
    adapters: VenueAdaptersDep,
) -> list[KindTestResponse]:
    try:
        results = connection_sync.test_connection(engine, settings, adapters, connection_id)
    except CredentialsUnreadableError as sealed:
        raise HTTPException(status_code=409, detail=str(sealed)) from sealed
    if results is None:
        raise HTTPException(status_code=404, detail="No such Connection.")
    return [KindTestResponse.of(result) for result in results]


class FuturesOutcomeResponse(BaseModel):
    new_fills: int
    new_funding: int


class ImportOutcomeResponse(BaseModel):
    batch_id: int | None
    created: int
    duplicates: int
    skipped: int
    # Created rows no provider could price at their own timestamp (ticket 41).
    unpriced: list[UnpricedRowResponse]
    price_conditions: list[PriceConditionResponse]


class CoveredPeriodResponse(BaseModel):
    start: AwareDatetime | None
    end: AwareDatetime


class KindSyncResponse(BaseModel):
    """One adapter kind's sync outcome. What landed stays reported beside an
    error where part of the kind refused — stored is never unreported."""

    adapter_kind: str
    ok: bool
    error: str | None
    futures: FuturesOutcomeResponse | None
    imported: ImportOutcomeResponse | None
    # The adapter's declared lookback the pull reached over — None where
    # nothing was pulled.
    covered_days: int | None
    # The period a broker's pull reports having covered — `start` null where
    # the venue served the Depot's history from its beginning.
    covered_period: CoveredPeriodResponse | None
    # What the venue stated that is no transaction — passed over by name,
    # for the Admin to record.
    passed_over: list[str]

    @classmethod
    def of(cls, result: connection_sync.KindSync) -> KindSyncResponse:
        return cls(
            adapter_kind=result.adapter_kind,
            ok=result.error is None,
            error=result.error,
            covered_days=result.covered_days,
            covered_period=None
            if result.covered_period is None
            else CoveredPeriodResponse(
                start=result.covered_period.start, end=result.covered_period.end
            ),
            passed_over=list(result.passed_over),
            futures=None
            if result.futures is None
            else FuturesOutcomeResponse(
                new_fills=result.futures.new_fills, new_funding=result.futures.new_funding
            ),
            imported=None
            if result.imported is None
            else ImportOutcomeResponse(
                batch_id=result.imported.batch_id,
                created=result.imported.created,
                duplicates=result.imported.duplicates,
                skipped=result.imported.skipped,
                unpriced=[UnpricedRowResponse.of(row) for row in result.imported.unpriced],
                price_conditions=[
                    PriceConditionResponse.of(entry) for entry in result.imported.price_conditions
                ],
            ),
        )


@router.post(
    "/connections/{connection_id}/sync",
    summary="Pull and land every kind the venue serves, reported per kind",
    response_model=list[KindSyncResponse],
)
def sync_connection(
    connection_id: int,
    admin: AdminDep,
    engine: EngineDep,
    settings: SettingsDep,
    adapters: VenueAdaptersDep,
    prices: PriceSourcesDep,
) -> list[KindSyncResponse]:
    try:
        results = connection_sync.sync_connection(
            engine, settings, adapters, connection_id, prices=prices
        )
    except CredentialsUnreadableError as sealed:
        raise HTTPException(status_code=409, detail=str(sealed)) from sealed
    if results is None:
        raise HTTPException(status_code=404, detail="No such Connection.")
    return [KindSyncResponse.of(result) for result in results]


# Fixed-point on the way out, as everywhere: a quantity is answered as a
# decimal string, never a float.
Fixed = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


class ReconcileRequest(BaseModel):
    # How far live may sit from tracked, in units of the Instrument, before
    # the line is a gap — None leaves the configured tolerance in force.
    tolerance: Annotated[Decimal, Field(ge=0)] | None = None


class ReconciliationLineResponse(BaseModel):
    """One Instrument's comparison. `difference` is live less tracked. An
    unresolved line is a venue symbol no single Instrument answers to: no
    Instrument, nothing tracked, and `detail` saying why."""

    instrument_id: int | None
    symbol: str
    name: str | None
    family: str | None
    live: Fixed
    tracked: Fixed | None
    difference: Fixed | None
    status: Literal["matched", "gap", "unresolved"]
    # The honest ways to close a gap — the app never closes one itself.
    resolutions: list[Literal["import_history", "opening_balance"]]
    detail: str | None


class KindReconciliationResponse(BaseModel):
    """One adapter kind's reconciliation against its paired Account — an
    error means nothing was compared."""

    adapter_kind: str
    ok: bool
    error: str | None
    account_id: int | None
    # The latest instant the venue's snapshot states.
    as_of: AwareDatetime | None
    tolerance: Fixed
    lines: list[ReconciliationLineResponse]

    @classmethod
    def of(cls, result: reconciliation.KindReconciliation) -> KindReconciliationResponse:
        return cls(
            adapter_kind=result.adapter_kind,
            ok=result.error is None,
            error=result.error,
            account_id=result.account_id,
            as_of=result.as_of,
            tolerance=result.tolerance,
            lines=[ReconciliationLineResponse(**vars(line)) for line in result.lines],
        )


@router.post(
    "/connections/{connection_id}/reconcile",
    summary="Compare what the venue says is held against what the transactions account for",
    response_model=list[KindReconciliationResponse],
)
def reconcile_connection(
    connection_id: int,
    admin: AdminDep,
    engine: EngineDep,
    settings: SettingsDep,
    adapters: VenueAdaptersDep,
    request: ReconcileRequest | None = None,
) -> list[KindReconciliationResponse]:
    """Reports and never repairs: a gap is left for the Admin to close by
    importing the missing history or recording an Opening Balance — nothing
    is written to the ledger from a venue's snapshot (ticket 39)."""
    try:
        results = reconciliation.reconcile_connection(
            engine,
            settings,
            adapters,
            connection_id,
            tolerance=None if request is None else request.tolerance,
        )
    except CredentialsUnreadableError as sealed:
        raise HTTPException(status_code=409, detail=str(sealed)) from sealed
    if results is None:
        raise HTTPException(status_code=404, detail="No such Connection.")
    return [KindReconciliationResponse.of(result) for result in results]


class PairAccountRequest(BaseModel):
    account_id: int


@router.put(
    "/connections/{connection_id}/pairings/{adapter_kind}",
    summary="Point one adapter kind at the Account it writes into",
    status_code=204,
)
def pair_account(
    connection_id: int,
    adapter_kind: NonBlank,
    request: PairAccountRequest,
    admin: AdminDep,
    engine: EngineDep,
) -> None:
    refused = connections.pair(engine, connection_id, adapter_kind, request.account_id)
    if refused is Refusal.no_such_connection:
        raise HTTPException(status_code=404, detail="No such Connection.")
    if refused is Refusal.no_such_account:
        raise HTTPException(status_code=404, detail="No such Account.")
    if refused is Refusal.foreign_platform:
        raise HTTPException(
            status_code=422,
            detail="That Account sits under another Platform — a Connection's data"
            " lands under its own.",
        )


@router.delete(
    "/connections/{connection_id}/pairings/{adapter_kind}",
    summary="Release an adapter kind's Account pairing",
    status_code=204,
)
def unpair_account(
    connection_id: int, adapter_kind: str, admin: AdminDep, engine: EngineDep
) -> None:
    if not connections.unpair(engine, connection_id, adapter_kind):
        raise HTTPException(status_code=404, detail="This kind is not paired.")
