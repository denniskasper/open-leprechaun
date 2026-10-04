"""Address imports over HTTP (ticket 38): the indexer registry as the picker
reads it, and the preview and commit of one public address. Everything here
is generic over the registry — adding a chain changes no line of this."""

from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints

from open_leprechaun.adapters import AddressIndexersDep
from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.prices import PriceSourcesDep
from open_leprechaun.repositories.imports import Refusal
from open_leprechaun.routers.imports import CommittedResponse, PreviewResponse
from open_leprechaun.services import address_imports
from open_leprechaun.services.address_imports import AddressRefused, IndexerFailed
from open_leprechaun.services.imports import CommitRefused

router = APIRouter(tags=["address-imports"])

# The registry key of the chain the Admin chose.
Chain = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# The public address, trimmed and otherwise exactly as given — a chain may
# write case-sensitive addresses, so nothing here folds case.
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class IndexerResponse(BaseModel):
    """One chain as the picker offers it, with the coin its network fees are
    paid in."""

    chain: str
    name: str
    native_symbol: str
    # How far back the indexer reaches, in days; None is the whole history.
    lookback_days: int | None


@router.get(
    "/address-indexers",
    summary="Every chain a public address can be read on",
    response_model=list[IndexerResponse],
)
def list_indexers(admin: AdminDep, indexers: AddressIndexersDep) -> list[IndexerResponse]:
    return [
        IndexerResponse(
            chain=indexer.chain,
            name=indexer.name,
            native_symbol=indexer.native.symbol,
            lookback_days=indexer.lookback_days,
        )
        for indexer in indexers.values()
    ]


class AddressRequest(BaseModel):
    """A chain, an address and the Account it lands in — no credential,
    because a chain's history is public."""

    chain: Chain
    address: Address
    account_id: int


@router.post(
    "/address-imports/preview",
    summary="What reading this address would create, without writing anything",
    response_model=PreviewResponse,
)
def preview_address(
    request: AddressRequest, admin: AdminDep, engine: EngineDep, indexers: AddressIndexersDep
) -> PreviewResponse:
    previewed = address_imports.preview(
        engine,
        indexers,
        chain=request.chain,
        address=request.address,
        account_id=request.account_id,
    )
    _refuse_unread(previewed)
    if previewed.refusal is not None and previewed.refusal.kind is Refusal.no_such_account:
        raise HTTPException(status_code=404, detail=previewed.refusal.sentence)
    return PreviewResponse.of(previewed)


@router.post(
    "/address-imports",
    summary="Commit this address's history as one reversible batch",
    status_code=201,
    response_model=CommittedResponse,
)
def commit_address(
    request: AddressRequest,
    admin: AdminDep,
    engine: EngineDep,
    indexers: AddressIndexersDep,
    prices: PriceSourcesDep,
) -> CommittedResponse:
    committed = address_imports.commit(
        engine,
        indexers,
        prices=prices,
        chain=request.chain,
        address=request.address,
        account_id=request.account_id,
    )
    _refuse_unread(committed)
    if isinstance(committed, CommitRefused):
        status = 404 if committed.kind is Refusal.no_such_account else 409
        raise HTTPException(status_code=status, detail=committed.sentence)
    return CommittedResponse.of(committed)


def _refuse_unread(outcome: object) -> None:
    """The three ways an address never reached the evaluation: no indexer
    for the chain, not an address there, or the chain not answering — the
    last one the chain's failure (502), never the request's."""
    if outcome is None:
        raise HTTPException(status_code=404, detail="No indexer reads this chain.")
    if isinstance(outcome, AddressRefused):
        raise HTTPException(status_code=422, detail=outcome.sentence)
    if isinstance(outcome, IndexerFailed):
        raise HTTPException(status_code=502, detail=outcome.sentence)
