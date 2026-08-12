"""What the application knows about Instruments beyond storage: the overview
that lets a reader tell two same-symbol rows apart, and the numéraire rule the
tax tickets read — whether moving an Instrument is itself a disposal."""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Engine

from open_leprechaun.repositories import instruments, stances


class CarriesNumeraireFlag(Protocol):
    """Anything that says whether it is the numéraire — a repository row or an
    overview alike."""

    @property
    def is_numeraire(self) -> bool: ...


def movement_is_disposal(instrument: CarriesNumeraireFlag) -> bool:
    """Whether moving this Instrument is itself a taxable disposal (ADR-0011).

    The numéraire is the one exception: every taxable figure is expressed in
    it, so its own movement creates no taxable event. The answer comes from
    the designation in the data — never from a symbol comparison — so another
    jurisdiction's numéraire is configuration, not a code change.
    """
    return not instrument.is_numeraire


@dataclass(frozen=True)
class Listing:
    id: int
    venue: str
    quote_currency: str
    # Whether this Listing's market prices the Instrument (ticket 45).
    price_source: bool


@dataclass(frozen=True)
class AccountStance:
    """One per-Account decision — `kept` or `ignored` (ADR-0012)."""

    account_id: int
    stance: str


@dataclass(frozen=True)
class InstrumentOverview:
    id: int
    family: str
    type: str
    symbol: str
    name: str
    chain: str | None
    contract_address: str | None
    isin: str | None
    is_numeraire: bool
    # A fund's Teilfreistellung category with the source of the value shown —
    # provider prefill or the Admin's own hand — and its distribution policy
    # (ticket 44). None means unclassified, which blocks report finalisation.
    fund_category: str | None
    fund_category_source: str | None
    distribution_policy: str | None
    # An Instrument an import auto-created for an unknown identifier waits
    # flagged until the Admin settles what it is.
    needs_review: bool
    listings: tuple[Listing, ...]
    # An ignored or dangerous position stays visible with a clear warning
    # rather than being hidden, so the stance travels with the overview.
    dangerous: bool
    stances: tuple[AccountStance, ...]


def overview(engine: Engine) -> list[InstrumentOverview]:
    listings_of: dict[int, list[Listing]] = {}
    for row in instruments.list_listings(engine):
        listings_of.setdefault(row.instrument_id, []).append(
            Listing(
                id=row.id,
                venue=row.venue,
                quote_currency=row.quote_currency,
                price_source=row.price_source,
            )
        )
    dangerous: set[int] = set()
    stances_of: dict[int, list[AccountStance]] = {}
    for row in stances.list_stances(engine):
        if row.account_id is None:
            dangerous.add(row.instrument_id)
        else:
            stances_of.setdefault(row.instrument_id, []).append(
                AccountStance(account_id=row.account_id, stance=row.stance)
            )
    return [
        InstrumentOverview(
            id=row.id,
            family=row.family,
            type=row.type,
            symbol=row.symbol,
            name=row.name,
            chain=row.chain,
            contract_address=row.contract_address,
            isin=row.isin,
            is_numeraire=row.is_numeraire,
            fund_category=row.fund_category,
            fund_category_source=row.fund_category_source,
            distribution_policy=row.distribution_policy,
            needs_review=row.needs_review,
            listings=tuple(listings_of.get(row.id, [])),
            dangerous=row.id in dangerous,
            stances=tuple(stances_of.get(row.id, [])),
        )
        for row in instruments.list_instruments(engine)
    ]
