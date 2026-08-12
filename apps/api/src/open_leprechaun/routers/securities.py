"""Adding and classifying security Instruments (ticket 44): search the
provider, pick a candidate or create by hand, record a fund's
Teilfreistellung classification with its source, and settle the review an
imported unknown identifier opened. Listings (ticket 45) join here: resolve
an identifier to the markets the provider knows, enter one by hand where no
provider does, and choose which Listing is the price source."""

from typing import Literal, Self

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, model_validator

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.market_data import SecurityResolutionDep
from open_leprechaun.ports.crypto_prices import ProviderOutageError, RateLimitedError
from open_leprechaun.repositories import instruments
from open_leprechaun.security_search import SecuritySearchDep
from open_leprechaun.services import securities
from open_leprechaun.services.securities import FUND_TYPES, FoundCandidate

router = APIRouter(tags=["securities"])

SecurityType = Literal["share", "etf", "fund", "bond", "certificate"]
FundCategory = Literal[
    "aktienfonds", "mischfonds", "immobilienfonds", "auslands_immobilienfonds", "sonstige"
]
CategorySource = Literal["provider", "admin"]
DistributionPolicy = Literal["distributing", "accumulating"]


class CandidateResponse(BaseModel):
    isin: str
    wkn: str | None
    ticker: str | None
    name: str
    type: str
    currency: str | None
    venue: str | None
    fund_category: str | None
    distribution_policy: str | None
    # The Instrument this candidate already is — the picker says so instead
    # of inviting a duplicate.
    instrument_id: int | None

    @classmethod
    def of(cls, found: FoundCandidate) -> Self:
        candidate = found.candidate
        return cls(
            isin=candidate.isin,
            wkn=candidate.wkn,
            ticker=candidate.ticker,
            name=candidate.name,
            type=candidate.type,
            currency=candidate.currency,
            venue=candidate.venue,
            fund_category=candidate.fund_category,
            distribution_policy=candidate.distribution_policy,
            instrument_id=found.instrument_id,
        )


class Classification(BaseModel):
    """A fund's Teilfreistellung category with the source of the value —
    always the two together — and its distribution policy. The source is the
    client's to state only at creation, where the picker relays whether the
    value is the provider's prefill or the Admin's own."""

    fund_category: FundCategory
    fund_category_source: CategorySource
    distribution_policy: DistributionPolicy | None = None


class AdminClassification(BaseModel):
    """A classification stated in the Admin's own act — an override or a
    review. The source is stamped `admin` on the server: an endpoint that is
    the Admin's hand must not let a request wear the provider's name."""

    fund_category: FundCategory
    distribution_policy: DistributionPolicy | None = None


class CreateSecurityRequest(BaseModel):
    isin: str
    name: str
    symbol: str
    type: SecurityType
    wkn: str | None = None
    ticker: str | None = None
    venue: str | None = None
    quote_currency: str | None = None
    classification: Classification | None = None

    @model_validator(mode="after")
    def well_formed(self) -> Self:
        if (self.venue is None) != (self.quote_currency is None):
            raise ValueError("A Listing names its venue and quote currency together.")
        if self.classification is not None and self.type not in FUND_TYPES:
            raise ValueError("A Teilfreistellung classification belongs to a fund.")
        return self


class CreatedResponse(BaseModel):
    id: int


class ReviewRequest(BaseModel):
    """The Admin settles an auto-created security: its real type and display
    metadata, and — where the type makes it a fund — its classification."""

    type: SecurityType
    symbol: str
    name: str
    classification: AdminClassification | None = None

    @model_validator(mode="after")
    def classification_belongs_to_funds(self) -> Self:
        if self.classification is not None and self.type not in FUND_TYPES:
            raise ValueError("A Teilfreistellung classification belongs to a fund.")
        return self


@router.get(
    "/securities/search",
    summary="Provider candidates for an ISIN, WKN, ticker or name, marked where already known",
    response_model=list[CandidateResponse],
)
def search_securities(
    admin: AdminDep,
    engine: EngineDep,
    provider: SecuritySearchDep,
    query: str = Query(min_length=2),
) -> list[CandidateResponse]:
    try:
        found = securities.search(engine, provider, query)
    except RateLimitedError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ProviderOutageError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return [CandidateResponse.of(entry) for entry in found]


@router.post(
    "/securities",
    status_code=201,
    summary="Create a security from a picked candidate, or by hand where no provider covers it",
    response_model=CreatedResponse,
)
def create_security(
    request: CreateSecurityRequest, admin: AdminDep, engine: EngineDep
) -> CreatedResponse:
    classification = request.classification
    created = instruments.create_security(
        engine,
        symbol=request.symbol,
        name=request.name,
        type=request.type,
        isin=request.isin,
        wkn=request.wkn,
        ticker=request.ticker,
        venue=request.venue,
        quote_currency=request.quote_currency,
        fund_category=classification.fund_category if classification else None,
        fund_category_source=classification.fund_category_source if classification else None,
        distribution_policy=classification.distribution_policy if classification else None,
    )
    if created is None:
        raise HTTPException(
            status_code=409, detail=f"An Instrument already carries the ISIN {request.isin}."
        )
    return CreatedResponse(id=created)


@router.put(
    "/securities/{instrument_id}/classification",
    status_code=204,
    summary="Record a fund's Teilfreistellung category, its source, and its distribution policy",
)
def classify_fund(
    instrument_id: int, request: AdminClassification, admin: AdminDep, engine: EngineDep
) -> None:
    instrument = instruments.get(engine, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="No such Instrument.")
    if instrument.type not in FUND_TYPES:
        raise HTTPException(
            status_code=422,
            detail="A Teilfreistellung classification belongs to a fund — this is"
            f" a {instrument.type}.",
        )
    if not instruments.classify_fund(
        engine,
        instrument_id,
        category=request.fund_category,
        source="admin",
        distribution_policy=request.distribution_policy,
    ):
        raise HTTPException(status_code=404, detail="No such Instrument.")


class ResolvedListingResponse(BaseModel):
    venue: str
    quote_currency: str


class CreateListingRequest(BaseModel):
    venue: str
    quote_currency: str
    # Whether this Listing takes over as the price source, displacing the
    # previous holder.
    price_source: bool = False


@router.get(
    "/securities/listings/resolve",
    summary="The Listings the provider knows for an identifier — empty where it knows none",
    response_model=list[ResolvedListingResponse],
)
def resolve_listings(
    admin: AdminDep,
    provider: SecurityResolutionDep,
    identifier: str = Query(min_length=2),
) -> list[ResolvedListingResponse]:
    try:
        resolved = provider.listings(identifier)
    except RateLimitedError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ProviderOutageError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return [
        ResolvedListingResponse(venue=listing.venue, quote_currency=listing.quote_currency)
        for listing in resolved
    ]


@router.post(
    "/securities/{instrument_id}/listings",
    status_code=201,
    summary="Enter a Listing by hand where no provider resolves it",
    response_model=CreatedResponse,
)
def create_listing(
    instrument_id: int, request: CreateListingRequest, admin: AdminDep, engine: EngineDep
) -> CreatedResponse:
    instrument = instruments.get(engine, instrument_id)
    if instrument is None or instrument.family != "security":
        raise HTTPException(status_code=404, detail="No such security.")
    created = instruments.add_listing(
        engine,
        instrument_id,
        venue=request.venue,
        quote_currency=request.quote_currency,
        price_source=request.price_source,
    )
    if created is None:
        raise HTTPException(
            status_code=409,
            detail=f"The {request.venue} / {request.quote_currency} Listing already exists.",
        )
    return CreatedResponse(id=created)


@router.put(
    "/securities/{instrument_id}/listings/{listing_id}/price-source",
    status_code=204,
    summary="Choose which Listing's market prices the Instrument",
)
def choose_price_source(
    instrument_id: int, listing_id: int, admin: AdminDep, engine: EngineDep
) -> None:
    if not instruments.set_price_source(engine, instrument_id, listing_id):
        raise HTTPException(status_code=404, detail="No such Listing under this Instrument.")


@router.put(
    "/securities/{instrument_id}/review",
    status_code=204,
    summary="Settle an auto-created security: choose its type and metadata, clearing the flag",
)
def review_security(
    instrument_id: int, request: ReviewRequest, admin: AdminDep, engine: EngineDep
) -> None:
    classification = request.classification
    if not instruments.resolve_review(
        engine,
        instrument_id,
        type=request.type,
        symbol=request.symbol,
        name=request.name,
        fund_category=classification.fund_category if classification else None,
        fund_category_source="admin" if classification else None,
        distribution_policy=classification.distribution_policy if classification else None,
    ):
        raise HTTPException(status_code=404, detail="No such security awaiting review.")
