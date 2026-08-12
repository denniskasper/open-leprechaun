"""Securities disposals (ticket 46): share and fund sales as §20 capital
income, derived from the ledger — never maintained beside it.

A disposal consumes Tax Lots FIFO within the Depot — the Account — and
Instrument that held them (§20 Abs. 4 Satz 7 EStG), on the same single
replay every disposal engine walks (services/disposals), so a disposal and
the lots it consumed can never disagree. No holding period ever exempts a
securities gain: §20 knows no Haltefrist, and §23 Abs. 2 EStG gives it
precedence. The gain is the proceeds less the Anschaffungskosten less the
sale's own costs (§20 Abs. 4 Satz 1 EStG), every component in EUR at the
reference rate of its own event date (ADR-0017) — which is what makes the
currency movement on a foreign-listed security part of the gain rather than
a separate item. A basis the derivation could not state — a purchase paid in
foreign cash — is stated here from the purchase's own legs, reached through
the slice's minting leg, at the acquisition date's rate.

What the producer knows ends at the event boundary (ADR-0013): each disposal
carries the category its instrument type demands — share sales into the
aktien pot (§20 Abs. 6 Satz 4 EStG), fund, bond and certificate gains into
the general pot — and, for a fund, the Teilfreistellung rate its category
selects from the per-year statutory store (§20 InvStG, ticket 09). The
engine (services/section20) reduces each disposal to one Section 20 Event
and alone applies exemption, netting, allowance and rate — no tax is
computed here.

A security still typed `unknown`, or a fund with no Teilfreistellung
classification, refuses by name rather than assuming a pot or a zero rate
(ticket 44): both are the Admin's to settle, like an unset statutory value —
unlike a valuation nothing can state yet, which is carried explicitly as
awaiting, never guessed at.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories.instruments import FUND_TYPES
from open_leprechaun.services import disposals, fx, lots
from open_leprechaun.services.statutory import required_value

__all__ = [
    "OTHER_CATEGORY",
    "PARTIAL_EXEMPTION_STATUTES",
    "SHARE_CATEGORY",
    "SecurityConsumption",
    "SecurityDisposal",
    "UnclassifiedSecurityError",
    "disposals_through",
]

SHARE_CATEGORY = "aktien"
"""Where a share sale's gain lands: the pot that holds share sales alone
(§20 Abs. 6 Satz 4 EStG)."""

OTHER_CATEGORY = "sonstige"
"""Where every other securities gain lands — funds, bonds, certificates are
general capital income."""

_CATEGORY_OF_TYPE = {
    "share": SHARE_CATEGORY,
    "etf": OTHER_CATEGORY,
    "fund": OTHER_CATEGORY,
    "bond": OTHER_CATEGORY,
    "certificate": OTHER_CATEGORY,
}
"""Which pot each security type's disposal feeds — routed by what the
instrument is, never by what any producer decides (ADR-0013). `unknown` is
deliberately absent: it refuses by name below."""

PARTIAL_EXEMPTION_STATUTES = {
    "aktienfonds": "§ 20 Abs. 1 Satz 1 InvStG",
    "mischfonds": "§ 20 Abs. 2 Satz 1 InvStG",
    "immobilienfonds": "§ 20 Abs. 3 Satz 1 Nr. 1 InvStG",
    "auslands_immobilienfonds": "§ 20 Abs. 3 Satz 1 Nr. 2 InvStG",
    "sonstige": "§ 20 InvStG",
}
"""The statute behind each fund category's per-year Teilfreistellung rate —
cited when a year's rate is unset, so the refusal names its law."""


class UnclassifiedSecurityError(Exception):
    """A disposed security cannot say how it is taxed — typed `unknown`, or
    a fund with no Teilfreistellung classification. Settling it is the
    Admin's act (ticket 44); computing over an assumption is nobody's."""


@dataclass(frozen=True)
class SecurityConsumption:
    """One lot slice a disposal consumed, FIFO within the Depot and
    Instrument. `gain_eur` is None while any component awaits a valuation —
    never a guess."""

    quantity: Decimal
    acquired_at: datetime
    basis_eur: Decimal | None
    basis_source: str
    proceeds_eur: Decimal | None
    costs_eur: Decimal | None
    gain_eur: Decimal | None


@dataclass(frozen=True)
class SecurityDisposal:
    """One securities disposal leg with everything it consumed, wearing the
    category and Teilfreistellung rate the engine will apply — stated here,
    applied there (ADR-0013). `gain_eur` is the disposal's gross gain, None
    while any consumption awaits a valuation."""

    leg_id: int
    account_id: int
    instrument_id: int
    disposed_at: datetime
    tax_year: int
    quantity: Decimal
    proceeds_eur: Decimal | None
    costs_eur: Decimal | None
    # Whether a consumed lot rests on an Opening Balance's declared estimate,
    # so a report can say which figures rest on an assumption.
    rests_on_estimate: bool
    category: str
    # The fund category's per-year Teilfreistellung rate (§20 InvStG) — zero
    # for everything that is not a fund.
    exemption_rate: Decimal
    gain_eur: Decimal | None
    consumptions: tuple[SecurityConsumption, ...]


def disposals_through(
    engine: Engine, source: ReferenceRateSource, *, through_year: int
) -> tuple[SecurityDisposal, ...]:
    """Every securities disposal up to the end of the Tax Year, derived from
    the beginning of time — FIFO has no shorter memory. A disposal exceeding
    the lots its Depot holds refuses whatever year the gap sits in: every
    later consumption's FIFO position rests on it."""
    walked = disposals.replay(engine)
    sold = []
    for transaction, leg, consumed in disposals.sales(walked, families=("security",)):
        disposals.refuse_shortfall(leg, consumed, transaction, walked.instruments)
        tax_year = fx.event_date(transaction.occurred_at).year
        if tax_year > through_year:
            continue
        instrument = walked.instruments[leg.instrument_id]
        category = _category(instrument)
        siblings = walked.legs_of.get(transaction.id, [])
        at = transaction.occurred_at
        proceeds = disposals.proceeds(
            engine, source, transaction, leg, siblings, walked.instruments
        )
        costs = disposals.costs(engine, source, leg, siblings, walked.instruments, at)
        proceeds_shares = disposals.prorated(proceeds, consumed, leg.quantity)
        costs_shares = disposals.prorated(costs, consumed, leg.quantity)
        consumptions = tuple(
            _consumption(
                piece,
                proceeds_share,
                costs_share,
                _basis(engine, source, walked, piece, instrument),
            )
            for piece, proceeds_share, costs_share in zip(
                consumed, proceeds_shares, costs_shares, strict=True
            )
        )
        awaiting = any(piece.gain_eur is None for piece in consumptions)
        sold.append(
            SecurityDisposal(
                leg_id=leg.id,
                account_id=leg.account_id,
                instrument_id=leg.instrument_id,
                disposed_at=at,
                tax_year=tax_year,
                quantity=leg.quantity,
                proceeds_eur=proceeds,
                costs_eur=costs,
                rests_on_estimate=any(piece.basis_source == lots.ESTIMATE for piece in consumed),
                category=category,
                exemption_rate=_exemption_rate(engine, instrument, year=tax_year),
                gain_eur=None
                if awaiting
                else sum((piece.gain_eur for piece in consumptions), Decimal(0)),
                consumptions=consumptions,
            )
        )
    return tuple(sold)


def _category(instrument: Row) -> str:
    if instrument.type == "unknown":
        raise UnclassifiedSecurityError(
            f"The security {instrument.symbol} is still typed unknown — settle its"
            " review before its disposal can say which pot the gain belongs to."
        )
    if instrument.type in FUND_TYPES and instrument.fund_category is None:
        raise UnclassifiedSecurityError(
            f"The fund {instrument.symbol} carries no Teilfreistellung classification —"
            " classify it before its disposal can state the exempt share."
        )
    return _CATEGORY_OF_TYPE[instrument.type]


def _exemption_rate(engine: Engine, instrument: Row, *, year: int) -> Decimal:
    """The Teilfreistellung the disposal's year grants this instrument: the
    fund category's configured rate (§20 InvStG) — a year whose rate is unset
    refuses by name — and zero, structurally, for everything not a fund."""
    if instrument.type not in FUND_TYPES:
        return Decimal(0)
    category = instrument.fund_category
    return required_value(
        engine,
        year=year,
        key=f"partial_exemption_{category}",
        statute=PARTIAL_EXEMPTION_STATUTES[category],
    )


def _consumption(
    piece: lots.Slice,
    proceeds_share: Decimal | None,
    costs_share: Decimal | None,
    basis_eur: Decimal | None,
) -> SecurityConsumption:
    if proceeds_share is None or costs_share is None or basis_eur is None:
        gain = None
    else:
        gain = proceeds_share - basis_eur - costs_share
    return SecurityConsumption(
        quantity=piece.quantity,
        acquired_at=piece.acquired_at,
        basis_eur=basis_eur,
        basis_source=piece.basis_source,
        proceeds_eur=proceeds_share,
        costs_eur=costs_share,
        gain_eur=gain,
    )


def _basis(
    engine: Engine,
    source: ReferenceRateSource,
    walked: disposals.Replay,
    piece: lots.Slice,
    instrument: Row,
) -> Decimal | None:
    """The consumed slice's Anschaffungskosten in EUR. A basis the derivation
    stated stands as stated; a purchase paid in something the ledger alone
    could not value is stated here from the purchase's own legs at the
    acquisition date's rate — the respective event date, §20 Abs. 4 Satz 1
    EStG. A lot minted by income at market value awaits what only a security
    price could state — None, never a guess."""
    if piece.basis_eur is not None:
        return piece.basis_eur
    if piece.basis_source == lots.COST and piece.minted_by_leg_id is not None:
        return _cost_at_acquisition(engine, source, walked, piece)
    if piece.basis_source == lots.MARKET_VALUE:
        return fx.value_eur(
            engine, source, instrument=instrument, quantity=piece.quantity, at=piece.acquired_at
        )
    return None


def _cost_at_acquisition(
    engine: Engine, source: ReferenceRateSource, walked: disposals.Replay, piece: lots.Slice
) -> Decimal | None:
    """What the purchase cost, valued at its own instant: the legs that left
    plus the fees charged against the acquisition (the same components
    services/lots._eur_cost reads), each by the reference rate of the
    acquisition date. Splitting one consideration across several positions
    needs their relative market values — None, never a guess.

    A partially consumed slice takes its share pro-rata at Decimal's default
    precision, like every report-time valuation: the slices of one lot are
    valued independently here, so a cents-rounded share could invent a cent
    across the halves of a lot — exact division cannot."""
    minting = walked.leg_by_id[piece.minted_by_leg_id]
    siblings = walked.legs_of.get(minting.transaction_id, [])
    if sum(sibling.role == "in" for sibling in siblings) > 1:
        return None
    total = disposals.valued_sum(
        engine,
        source,
        [
            sibling
            for sibling in siblings
            if sibling.role == "out"
            or (sibling.role == "fee" and sibling.charged_against_leg_id == minting.id)
        ],
        walked.instruments,
        piece.acquired_at,
    )
    if total is None or piece.quantity == minting.quantity:
        return total
    return total * piece.quantity / minting.quantity
