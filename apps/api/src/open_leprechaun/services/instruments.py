"""What the application knows about Instruments beyond storage: the overview
that lets a reader tell two same-symbol rows apart, the numéraire rule the
tax tickets read — whether moving an Instrument is itself a disposal — and
the rule for taking one back, which is refused in words the Admin can act
on."""

from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import Engine

from open_leprechaun.repositories import imports, instruments, stances
from open_leprechaun.repositories.instruments import Refusal


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
class Deployment:
    """One chain's contract a token is (ADR-0032)."""

    chain: str
    contract_address: str


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
    # A token's identities, one per chain, the home one first (ADR-0032);
    # empty for anything that is not a token.
    deployments: tuple[Deployment, ...]
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
    deployments_of: dict[int, list[Deployment]] = {}
    for row in instruments.list_deployments(engine):
        deployments_of.setdefault(row.instrument_id, []).append(
            Deployment(chain=row.chain, contract_address=row.contract_address)
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
            deployments=tuple(deployments_of.get(row.id, [])),
            dangerous=row.id in dangerous,
            stances=tuple(stances_of.get(row.id, [])),
        )
        for row in instruments.list_instruments(engine)
    ]


@dataclass(frozen=True)
class AlreadyExists:
    """The identity the Admin stated is one the ledger already holds — named,
    so the refusal says which Instrument answers to it."""

    symbol: str
    name: str


def add_by_hand(
    engine: Engine,
    *,
    kind: Literal["token", "native", "cash"],
    symbol: str,
    name: str,
    chain: str | None = None,
    contract_address: str | None = None,
    pegged_currency: str | None = None,
) -> int | AlreadyExists:
    """A coin, token or currency the Admin states by its identity (ADR-0010)
    — what a venue's sync, stating a symbol alone, can resolve but never
    create. The unique indexes are the arbiter: where the identity exists,
    the Instrument holding it is answered instead of a second one."""
    if kind == "token":
        assert chain is not None and contract_address is not None
        created = instruments.create_crypto_token(
            engine,
            symbol=symbol,
            name=name,
            chain=chain,
            contract_address=contract_address,
            pegged_currency=pegged_currency,
        )
    elif kind == "native":
        assert chain is not None
        created = instruments.create_native_coin(engine, symbol=symbol, name=name, chain=chain)
    else:
        created = instruments.create_cash(engine, symbol=symbol, name=name)
    if created is not None:
        return created
    existing_id = imports.find_instrument(
        engine, kind=kind, symbol=symbol, chain=chain, contract_address=contract_address
    )
    existing = None if existing_id is None else instruments.get(engine, existing_id)
    if existing is None:
        raise RuntimeError(
            f"The {kind} {symbol!r} was refused, yet no Instrument holds its identity."
        )
    return AlreadyExists(symbol=existing.symbol, name=existing.name)


@dataclass(frozen=True)
class Refused:
    """A removal the rule refused: nothing was deleted, and the reason says
    what keeps the Instrument — in words, never in counts."""

    reason: str


# What each kind of ledger fact is called where a refusal names it.
_KIND_OF_RECORD = {
    "transaction_leg": "transactions",
    "futures_fill": "futures fills",
    "funding_payment": "funding payments",
    "futures_position": "futures positions",
    "capital_income": "capital income",
    "corporate_action": "corporate actions",
}


def remove_instrument(engine: Engine, instrument_id: int) -> Refused | Refusal | None:
    """An Instrument may be removed only while nothing in the ledger refers to
    it — the repair for a mistyped identity, which is never edited because it
    is what the Instrument is (ADR-0010). The numéraire never goes: every
    figure is expressed in it. A refusal names the kinds of record in the way
    and never how many there are. None means it is gone."""
    held = instruments.delete_instrument(engine, instrument_id)
    if held is Refusal.numeraire:
        numeraire = instruments.get(engine, instrument_id)
        assert numeraire is not None
        return Refused(f"{numeraire.symbol} is the numéraire, so it stays for good.")
    if not isinstance(held, instruments.InstrumentHolders):
        return held
    named = [_KIND_OF_RECORD[use] for use in held.uses]
    listed = named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"
    return Refused(f"This Instrument stays for good: it is recorded in {listed}.")


def attach_deployment(
    engine: Engine, instrument_id: int, *, chain: str, contract_address: str
) -> Refused | None:
    """Another chain's contract of the same token, attached by the Admin
    (ADR-0032) — only one its issuer mints itself, which the ledger cannot
    tell from the contract and so never decides. A contract that already
    names another Instrument is refused with that Instrument named: two
    Instruments become one only by settling the newer as a Deployment of the
    older. None means attached; a missing Instrument raises LookupError."""
    refused = instruments.add_deployment(
        engine, instrument_id, chain=chain, contract_address=contract_address
    )
    if refused is instruments.DeploymentRefusal.no_such_instrument:
        raise LookupError(instrument_id)
    if refused is instruments.DeploymentRefusal.not_a_token:
        return Refused(
            "Only a token has Deployments — a coin's symbol already names it on every chain,"
            " and a security or currency is on none."
        )
    if refused is instruments.DeploymentRefusal.already_held:
        holder = instruments.holding_deployment(
            engine, chain=chain, contract_address=contract_address
        )
        if holder is None or holder.id == instrument_id:
            return Refused("This Instrument already has that Deployment.")
        return Refused(
            f"{holder.name} ({holder.symbol}) already holds this contract. Settle it as a"
            " Deployment of this Instrument instead."
        )
    return None


def settle_as_deployment_of(engine: Engine, newer: int, older: int) -> Refused | None:
    """The Admin's answer that a token the ledger met by an unfamiliar
    contract is another token it already holds, on another chain
    (ADR-0032). Its inflows then wait under that token, and are settled
    there. None means settled; a missing Instrument raises LookupError."""
    refused = instruments.fold_into(engine, newer, older)
    if refused is instruments.FoldRefusal.no_such_instrument:
        raise LookupError(newer)
    if refused is instruments.FoldRefusal.not_two_tokens:
        return Refused("Only a token settles as a Deployment, and only of another token.")
    if refused is instruments.FoldRefusal.decided:
        return Refused(
            "A token settles as a Deployment of another only while nothing about it has been"
            " decided — no Stance, and nothing recorded but inflows still waiting."
        )
    return None
