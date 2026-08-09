"""The §20 EStG capital-income engine, first half (ticket 26): the one
Section 20 Event shape every source of capital income reduces to, and the
netting that consumes it (ADR-0013). No producer knows anything about
categories' treatment, allowances or rates — it emits events, and the
engine alone decides.

Per year the engine groups events by Verlustverrechnungstopf, nets within
each — a loss in one category never offsets a gain in another (§20 Abs. 6
EStG) — and applies that category's per-year loss cap, read from the
statutory store (ticket 09), never from a constant. Teilfreistellung
(§20 InvStG) exempts its share of an event's gross before the event enters
its category.

The second half (ticket 27) finishes the ADR-0013 order: each category
carries its unused loss forward across years — never into another category
— and can open with a balance from an assessment predating the ledger;
what survives every pot is summed; the Sparerpauschbetrag is deducted once
from that combined total, less whatever a Freistellungsauftrag already
consumed at source; and the flat rate, the solidarity surcharge and — where
elected — church tax with its exact deduction effect produce the figure
that belongs on the return. A personal-rate comparison (§32d Abs. 6 EStG)
is noted, never computed (ADR-0007).

`net`, `carry` and `assess` are pure functions of events and configuration
with no database dependency, so every statutory rule has a test naming its
paragraph and failing alone.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import Engine

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.repositories import statutory as statutory_repository
from open_leprechaun.services import futures, fx, lots
from open_leprechaun.services.stances import income_excluding_stance
from open_leprechaun.services.statutory import (
    church_tax_rate_key,
    optional_values,
    required_value,
    saver_allowance_key,
)
from open_leprechaun.services.tax_treatment import SECTION_20, TAX_CONSEQUENCES

__all__ = [
    "CATEGORIES",
    "FUTURES_CATEGORY",
    "LOSS_CAP_KEYS",
    "NO_GERMAN_WITHHOLDING",
    "OPENING_CARRYFORWARD_KEYS",
    "PERSONAL_RATE_NOTE",
    "CarriedCategory",
    "CarryforwardLayer",
    "CategoryBalance",
    "CategoryEntry",
    "ExcludedEvent",
    "ForeignWithholding",
    "GermanWithholding",
    "Section20Assessment",
    "Section20Event",
    "Section20Year",
    "TaxDue",
    "assess",
    "carry",
    "net",
    "year_report",
]

CATEGORIES = ("aktien", "sonstige", "termingeschaefte")
"""The Verlustverrechnungstöpfe, in the order the report states them:
share sales (§20 Abs. 6 Satz 4 EStG), everything else capital — funds,
bonds, interest, dividends, Vorabpauschale — and Termingeschäfte."""

LOSS_CAP_KEYS = {category: f"loss_cap_{category}" for category in CATEGORIES}
"""Each category's per-year loss cap in the statutory vocabulary (ticket
09) — optional there, because an absent cap means uncapped, never unknown
(JStG 2024 struck the §20 Abs. 6 Satz 5/6 caps for all open cases)."""

OPENING_CARRYFORWARD_KEYS = {
    category: f"opening_carryforward_{category}" for category in CATEGORIES
}
"""Each category's opening loss carryforward in the statutory vocabulary:
the balance a category opens the entered year with, from a loss assessment
predating the ledger (ADR-0013). Optional — absent means zero, never
unknown."""


@dataclass(frozen=True)
class GermanWithholding:
    """Kapitalertragsteuer at source, split into its components — zero until
    a withholding producer (ticket 43) states what was actually taken."""

    kapitalertragsteuer_eur: Decimal
    solidarity_surcharge_eur: Decimal
    church_tax_eur: Decimal


NO_GERMAN_WITHHOLDING = GermanWithholding(Decimal(0), Decimal(0), Decimal(0))


@dataclass(frozen=True)
class ForeignWithholding:
    """Quellensteuer with its source country — creditability depends on
    which country withheld, so the two travel together."""

    amount_eur: Decimal
    country: str


@dataclass(frozen=True)
class Section20Event:
    """The one shape every source of capital income reduces to (ADR-0013):
    futures closes, share and fund disposals, dividends, distributions,
    interest and Vorabpauschale are all emitters. `date` is the Europe/Berlin
    calendar date that buckets the tax year (services/fx.event_date);
    `source` names the producing record, e.g. "leg:42"."""

    date: date
    category: str
    gross_eur: Decimal
    # The Teilfreistellung rate (§20 InvStG), a fraction of one — 0 where
    # none applies.
    exemption_rate: Decimal
    german_withholding: GermanWithholding
    foreign_withholding: ForeignWithholding | None
    source: str


@dataclass(frozen=True)
class CategoryEntry:
    """One event as its pot counted it: the event verbatim, and what of it
    entered — the gross less its Teilfreistellung share — so every balance
    is traceable to the records that produced it."""

    event: Section20Event
    counted_eur: Decimal


@dataclass(frozen=True)
class CategoryBalance:
    """One category's answer for the year: the pot netted, then bounded by
    its per-year loss cap. `cap_eur` is the year's configured cap — None
    means uncapped, never unknown (JStG 2024 struck the §20 Abs. 6 Satz 5/6
    caps for all open cases). `balance_eur` is the figure for the form line;
    `loss_beyond_cap_eur` is the loss the cap held back this year — what
    carryforward (ticket 27) will pick up."""

    category: str
    entries: tuple[CategoryEntry, ...]
    net_eur: Decimal
    cap_eur: Decimal | None
    balance_eur: Decimal
    loss_beyond_cap_eur: Decimal


_CENT = Decimal("0.01")


def net(
    events: Iterable[Section20Event], *, year: int, caps: Mapping[str, Decimal]
) -> tuple[CategoryBalance, ...]:
    """The first half of the engine, pure: group the year's events by
    category, net within each, apply that category's per-year loss cap.
    Only events dated in the year count — the date is Europe/Berlin local,
    the clock every tax figure keeps (services/fx.event_date). `caps` maps
    a category to its per-year cap — an absent category is uncapped."""
    entries_of: dict[str, list[CategoryEntry]] = {category: [] for category in CATEGORIES}
    for event in events:
        if event.category not in entries_of:
            raise ValueError(
                f"A Section 20 Event knows no category {event.category!r} —"
                f" the pots are {', '.join(CATEGORIES)}."
            )
        if event.date.year != year:
            continue
        entries_of[event.category].append(CategoryEntry(event=event, counted_eur=_counted(event)))
    balances = []
    for category in CATEGORIES:
        entries = tuple(entries_of[category])
        total = sum((entry.counted_eur for entry in entries), Decimal(0))
        cap = caps.get(category)
        recognised = max(total, -cap) if cap is not None and total < 0 else total
        balances.append(
            CategoryBalance(
                category=category,
                entries=entries,
                net_eur=total,
                cap_eur=cap,
                balance_eur=recognised,
                loss_beyond_cap_eur=recognised - total,
            )
        )
    return tuple(balances)


def _counted(event: Section20Event) -> Decimal:
    """What of the event enters its pot: the gross less the Teilfreistellung
    share (§20 InvStG) — exempting income and loss alike (§21 InvStG). Cents
    only where a rate actually splits the amount; a rate of zero leaves the
    gross exact."""
    if event.exemption_rate == 0:
        return event.gross_eur
    return (event.gross_eur * (1 - event.exemption_rate)).quantize(_CENT, ROUND_HALF_EVEN)


@dataclass(frozen=True)
class CarryforwardLayer:
    """One slice of a category's loss carryforward, wearing the year that
    established it — the pot is one amount in law (§20 Abs. 6 Satz 3 EStG),
    layered here so a consumption can name the year it came from. An opening
    layer was entered from an assessment predating the ledger and wears the
    year it was entered for."""

    origin_year: int
    amount_eur: Decimal
    opening: bool = False


@dataclass(frozen=True)
class CarriedCategory:
    """One category's year with its carryforward rolled: what it walked in
    with, what the year's gain consumed (each slice naming its origin year),
    what this year's loss added, what survives into the combined total, and
    what walks on. A negative pot survives as nothing — its loss carries,
    never crossing into another category."""

    category: str
    carryforward_in: tuple[CarryforwardLayer, ...]
    consumed: tuple[CarryforwardLayer, ...]
    produced_eur: Decimal
    surviving_eur: Decimal
    carryforward_out: tuple[CarryforwardLayer, ...]


def carry(
    balances: Iterable[CategoryBalance],
    *,
    year: int,
    carryforward_in: Mapping[str, tuple[CarryforwardLayer, ...]] | None = None,
    openings: Mapping[str, Decimal] | None = None,
) -> tuple[CarriedCategory, ...]:
    """Roll one year's category balances through their carryforwards (§20
    Abs. 6 Satz 2 und 3 EStG), each category strictly inside itself. An
    opening balance configured for this year enters as the oldest layer — a
    loss established before the ledger existed still shelters income here
    (ADR-0013); absent means zero. A gain consumes layers oldest first, and
    where the year's cap is configured it bounds the consumption exactly as
    it bounds a recognised loss (§20 Abs. 6 Satz 5 EStG as configured); a
    net loss carries forward in full — the cap bounds offsetting, never the
    carrying."""
    carried = []
    for balance in balances:
        opening = (openings or {}).get(balance.category, Decimal(0))
        layers = list((carryforward_in or {}).get(balance.category, ()))
        if opening:
            layers.insert(0, CarryforwardLayer(origin_year=year, amount_eur=opening, opening=True))
        gain = balance.balance_eur if balance.balance_eur > 0 else Decimal(0)
        consumable = min(gain, sum((layer.amount_eur for layer in layers), Decimal(0)))
        if balance.cap_eur is not None:
            consumable = min(consumable, balance.cap_eur)
        consumed, remaining = _eaten(layers, consumable)
        produced = -balance.net_eur if balance.net_eur < 0 else Decimal(0)
        if produced:
            remaining.append(CarryforwardLayer(origin_year=year, amount_eur=produced))
        carried.append(
            CarriedCategory(
                category=balance.category,
                carryforward_in=tuple(layers),
                consumed=consumed,
                produced_eur=produced,
                surviving_eur=gain - consumable,
                carryforward_out=tuple(remaining),
            )
        )
    return tuple(carried)


def _eaten(
    layers: list[CarryforwardLayer], amount: Decimal
) -> tuple[tuple[CarryforwardLayer, ...], list[CarryforwardLayer]]:
    """The layers split by a consumption: what was eaten, oldest first, and
    what remains — a partly eaten layer keeps its origin on both sides."""
    consumed = []
    remaining = []
    for layer in layers:
        bite = min(layer.amount_eur, amount)
        amount -= bite
        if bite:
            consumed.append(
                CarryforwardLayer(
                    origin_year=layer.origin_year, amount_eur=bite, opening=layer.opening
                )
            )
        if layer.amount_eur > bite:
            remaining.append(
                CarryforwardLayer(
                    origin_year=layer.origin_year,
                    amount_eur=layer.amount_eur - bite,
                    opening=layer.opening,
                )
            )
    return tuple(consumed), remaining


PERSONAL_RATE_NOTE = (
    "Assessment at the personal rate (Günstigerprüfung, § 32d Abs. 6 EStG) may"
    " yield less tax and can be requested on the return — this report does not"
    " compute it."
)
"""The note every assessment carries (ADR-0007): the comparison exists, the
return can ask for it, and this application deliberately computes only the
flat scheme."""


@dataclass(frozen=True)
class TaxDue:
    """The euro figures the flat scheme owes on the taxable amount — stated
    here because the rate is statutory, the one regime where ADR-0007 lets a
    euro of tax be spoken."""

    income_tax_eur: Decimal
    solidarity_surcharge_eur: Decimal
    church_tax_eur: Decimal
    total_eur: Decimal


@dataclass(frozen=True)
class Section20Assessment:
    """The year's §20 answer past the pots: each category rolled through its
    carryforward, the surviving combined total, the allowance applied once
    across it — never per source, and never past what exemption orders left —
    the taxable remainder, and the tax the flat scheme owes on it."""

    year: int
    categories: tuple[CarriedCategory, ...]
    combined_eur: Decimal
    allowance_eur: Decimal
    allowance_used_at_source_eur: Decimal
    allowance_applied_eur: Decimal
    taxable_eur: Decimal
    tax: TaxDue
    personal_rate_note: str


def assess(
    carried: tuple[CarriedCategory, ...],
    *,
    year: int,
    allowance_eur: Decimal,
    allowance_used_at_source_eur: Decimal,
    flat_rate: Decimal,
    solidarity_surcharge_rate: Decimal,
    church_tax_rate: Decimal | None,
) -> Section20Assessment:
    """Finish the year: sum what survives every category, deduct the
    Sparerpauschbetrag once across that combined total (§20 Abs. 9 EStG) —
    only what exemption orders have not already consumed at source, and never
    below zero (Satz 4) — then apply the rate. With church tax elected the
    income tax is taxable / (1/rate + church rate): the §32d Abs. 1 Satz 4
    formula carrying the church-tax deduction exactly, not an approximation.
    `church_tax_rate` is None where none is elected — no rate, not a zero
    one."""
    combined = sum((category.surviving_eur for category in carried), Decimal(0))
    applied = min(combined, max(allowance_eur - allowance_used_at_source_eur, Decimal(0)))
    taxable = combined - applied
    if church_tax_rate is None:
        income_tax = (taxable * flat_rate).quantize(_CENT, ROUND_HALF_EVEN)
        church_tax = Decimal(0)
    else:
        income_tax = (taxable / (1 / flat_rate + church_tax_rate)).quantize(_CENT, ROUND_HALF_EVEN)
        church_tax = (income_tax * church_tax_rate).quantize(_CENT, ROUND_HALF_EVEN)
    surcharge = (income_tax * solidarity_surcharge_rate).quantize(_CENT, ROUND_HALF_EVEN)
    return Section20Assessment(
        year=year,
        categories=carried,
        combined_eur=combined,
        allowance_eur=allowance_eur,
        allowance_used_at_source_eur=allowance_used_at_source_eur,
        allowance_applied_eur=applied,
        taxable_eur=taxable,
        tax=TaxDue(
            income_tax_eur=income_tax,
            solidarity_surcharge_eur=surcharge,
            church_tax_eur=church_tax,
            total_eur=income_tax + surcharge + church_tax,
        ),
        personal_rate_note=PERSONAL_RATE_NOTE,
    )


@dataclass(frozen=True)
class ExcludedEvent:
    """One §20-typed receipt the year refused, named so the balances beside
    it can never silently hide it: the position's stance keeps the income
    out exactly as it keeps the lot unminted (services/stances). An
    unacknowledged one waits in the inbox on the Admin's decision; an
    ignored or dangerous one never enters."""

    leg_id: int
    type: str
    account_id: int
    instrument_id: int
    received_at: datetime
    stance: str


@dataclass(frozen=True)
class Section20Year:
    """One Tax Year's capital income: the three category balances and the
    assessment past them — carryforward, allowance, rate — with what stance
    kept out stated beside them. While any event up to the year's end awaits
    a crypto price (ticket 18) the year states no balances and no assessment
    — netting around a missing member could flip a pot's sign, and a prior
    year's unvalued loss would falsify every carryforward after it — and
    names what it waits on in the events' own source vocabulary ("leg:42",
    "futures_position:7")."""

    year: int
    balances: tuple[CategoryBalance, ...] | None
    assessment: Section20Assessment | None
    excluded: tuple[ExcludedEvent, ...]
    awaiting_valuation: tuple[str, ...]


_CATEGORY_OF = {"dividend": "sonstige", "distribution": "sonstige", "interest": "sonstige"}
"""Which pot each §20-typed transaction feeds — all three in the general
pot, because the aktien pot holds share *sales* alone (§20 Abs. 6 Satz 4
EStG) and Termingeschäfte their own. Futures positions (ticket 28) emit
into theirs below; share disposals (ticket 46) will too. The emitters know
what they are, never how the pots treat them (ADR-0013)."""

FUTURES_CATEGORY = "termingeschaefte"
"""Where every futures close lands (§20 Abs. 2 Satz 1 Nr. 3 EStG): its own
Verlustverrechnungstopf (§20 Abs. 6 Satz 5 EStG as configured)."""


def year_report(engine: Engine, source: ReferenceRateSource, *, year: int) -> Section20Year:
    """The §20 answer for one Tax Year: the ledger's capital income up to the
    year's end reduced to Section 20 Events — withholding empty until tickets
    43 and 47 state what was taken at source — then run through the whole
    engine. Carryforward makes this a chain: every year from the earliest
    event or configured opening carryforward is netted and rolled under its
    own configured caps, so the target year opens with exactly what its
    predecessors left. The allowance and the rates are the target year's,
    selected by the Admin's election; what a Freistellungsauftrag consumed at
    source stays zero until ticket 43 states it. Teilfreistellung stays zero
    here because no fund Instrument exists yet (ticket 44); once one does, a
    fund with no classification must block finalisation rather than silently
    assume a zero rate (CONTEXT.md, tickets 46/47)."""
    election = statutory_repository.election(engine)
    allowance = required_value(
        engine,
        year=year,
        key=saver_allowance_key(election.filing_status),
        statute="§20 Abs. 9 EStG",
    )
    flat_rate = required_value(
        engine, year=year, key="flat_rate", statute="§32d Abs. 1 Satz 1 EStG"
    )
    surcharge_rate = required_value(
        engine, year=year, key="solidarity_surcharge_rate", statute="§4 Satz 1 SolzG 1995"
    )
    church_key = church_tax_rate_key(election.church_tax)
    church_rate = (
        required_value(engine, year=year, key=church_key, statute="KiStG der Länder")
        if church_key is not None
        else None
    )
    caps_of = {
        category: optional_values(engine, key=key) for category, key in LOSS_CAP_KEYS.items()
    }
    openings_of = {
        category: optional_values(engine, key=key)
        for category, key in OPENING_CARRYFORWARD_KEYS.items()
    }
    with lots.snapshot(engine) as connection:
        transaction_rows, leg_rows = lots_repository.ledger(connection)
        stance_rows = lots_repository.stance_rows(connection)
        instrument_rows = lots_repository.instrument_rows(connection)
        futures_rows = futures_repository.closed_position_rows(connection)
    instruments = {row.id: row for row in instrument_rows}
    decisions_of = lots.grouped(stance_rows, "instrument_id")
    legs_of = lots.grouped(leg_rows, "transaction_id")

    events = []
    excluded = []
    awaiting = []
    for transaction in transaction_rows:
        if TAX_CONSEQUENCES[transaction.type].income != SECTION_20:
            continue
        event_year = fx.event_date(transaction.occurred_at).year
        if event_year > year:
            continue
        for leg in legs_of.get(transaction.id, []):
            if leg.role != "in":
                continue
            stance = income_excluding_stance(
                instrument=instruments[leg.instrument_id],
                decisions=decisions_of.get(leg.instrument_id, ()),
                account_id=leg.account_id,
            )
            if stance is not None:
                # A prior year's exclusion is that year's own report's to
                # name; this year states only what it kept out itself.
                if event_year == year:
                    excluded.append(
                        ExcludedEvent(
                            leg_id=leg.id,
                            type=transaction.type,
                            account_id=leg.account_id,
                            instrument_id=leg.instrument_id,
                            received_at=transaction.occurred_at,
                            stance=stance,
                        )
                    )
                continue
            gross = fx.value_eur(
                engine,
                source,
                instrument=instruments[leg.instrument_id],
                quantity=leg.quantity,
                at=transaction.occurred_at,
            )
            if gross is None:
                awaiting.append(f"leg:{leg.id}")
                continue
            events.append(
                Section20Event(
                    date=fx.event_date(transaction.occurred_at),
                    category=_CATEGORY_OF[transaction.type],
                    gross_eur=gross,
                    exemption_rate=Decimal(0),
                    german_withholding=NO_GERMAN_WITHHOLDING,
                    foreign_withholding=None,
                    source=f"leg:{leg.id}",
                )
            )

    # Futures (ticket 28, ADR-0009): a closed position emits one event for
    # its net figure — realised result less trading fees plus attributed
    # funding — into the Termingeschäfte pot, and computes no tax of its own
    # (ADR-0013). The position counts in the year it closed, by the Berlin
    # clock; an open position never reaches here and counts in no year. The
    # net converts at the close date — the instant the result was realised —
    # by whatever the reference-rate universe can state for the settlement
    # Instrument; a settlement only a crypto price can value waits exactly
    # like an unvalued leg. Stance plays no part: the result is capital
    # income however its settlement currency is regarded as a holding.
    for position in futures_rows:
        if fx.event_date(position.closed_at).year > year:
            continue
        net_result = futures.net_figure(position)
        gross = fx.value_eur(
            engine,
            source,
            instrument=instruments[position.settlement_instrument_id],
            quantity=net_result,
            at=position.closed_at,
        )
        if gross is None:
            awaiting.append(f"futures_position:{position.id}")
            continue
        events.append(
            Section20Event(
                date=fx.event_date(position.closed_at),
                category=FUTURES_CATEGORY,
                gross_eur=gross,
                exemption_rate=Decimal(0),
                german_withholding=NO_GERMAN_WITHHOLDING,
                foreign_withholding=None,
                source=f"futures_position:{position.id}",
            )
        )

    if awaiting:
        return Section20Year(
            year=year,
            balances=None,
            assessment=None,
            excluded=tuple(excluded),
            awaiting_valuation=tuple(awaiting),
        )

    first = min(
        [
            year,
            *(event.date.year for event in events),
            *(y for years in openings_of.values() for y in years if y <= year),
        ]
    )
    carryforward: dict[str, tuple[CarryforwardLayer, ...]] = {}
    for chained_year in range(first, year + 1):
        balances = net(
            events,
            year=chained_year,
            caps={
                category: caps_of[category][chained_year]
                for category in CATEGORIES
                if chained_year in caps_of[category]
            },
        )
        carried = carry(
            balances,
            year=chained_year,
            carryforward_in=carryforward,
            openings={
                category: openings_of[category][chained_year]
                for category in CATEGORIES
                if chained_year in openings_of[category]
            },
        )
        carryforward = {pot.category: pot.carryforward_out for pot in carried}

    return Section20Year(
        year=year,
        balances=balances,
        assessment=assess(
            carried,
            year=year,
            allowance_eur=allowance,
            allowance_used_at_source_eur=Decimal(0),
            flat_rate=flat_rate,
            solidarity_surcharge_rate=surcharge_rate,
            church_tax_rate=church_rate,
        ),
        excluded=tuple(excluded),
        awaiting_valuation=(),
    )
