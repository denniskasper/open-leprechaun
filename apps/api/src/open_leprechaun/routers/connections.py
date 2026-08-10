"""Connections over HTTP: credentials go in once, and no response ever
carries secret material in any form (ADR-0003) — the request model is the
last time the API sees a key, a secret or a passphrase in the clear."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.ports.venues import VENUES
from open_leprechaun.services import connections
from open_leprechaun.services.connections import ConnectionOverview, Refusal
from open_leprechaun.settings import SettingsDep

router = APIRouter(tags=["connections"])

# Labels and keys arrive from a human pasting; trimmed before a stray space
# can become part of an identity or a credential.
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class VenueResponse(BaseModel):
    venue: str
    name: str
    # UI copy: the read-only permission set to grant when minting the key.
    required_scope: str
    requires_secret: bool
    requires_passphrase: bool


class AdapterStatusResponse(BaseModel):
    adapter_kind: str
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None


class ConnectionResponse(BaseModel):
    """Everything the Admin ever sees of a Connection again: a label, a
    fingerprint, a last-used timestamp and per-kind results. Deliberately no
    field that could carry secret material."""

    id: int
    platform_id: int
    venue: str
    label: str
    fingerprint: str
    last_used_at: datetime | None
    statuses: list[AdapterStatusResponse]

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
