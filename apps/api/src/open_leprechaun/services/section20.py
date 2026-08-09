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
its category. Carryforward across years, the Sparerpauschbetrag and the
rate are the second half, ticket 27.

`net` is a pure function of events and configuration with no database
dependency, so every statutory rule has a test naming its paragraph and
failing alone.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import Engine

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.services import fx, lots
from open_leprechaun.services.stances import income_excluding_stance
from open_leprechaun.services.statutory import optional_value
from open_leprechaun.services.tax_treatment import SECTION_20, TAX_CONSEQUENCES

__all__ = [
    "CATEGORIES",
    "LOSS_CAP_KEYS",
    "NO_GERMAN_WITHHOLDING",
    "CategoryBalance",
    "CategoryEntry",
    "ExcludedEvent",
    "ForeignWithholding",
    "GermanWithholding",
    "Section20Event",
    "Section20Year",
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
    """One Tax Year's capital income as far as ticket 26 reaches: the three
    category balances, with what stance kept out stated beside them. While
    any event awaits a crypto price (ticket 18) the year states no balances
    — netting around a missing member could flip a pot's sign — and names
    the legs it waits on."""

    year: int
    balances: tuple[CategoryBalance, ...] | None
    excluded: tuple[ExcludedEvent, ...]
    awaiting_valuation: tuple[int, ...]


_CATEGORY_OF = {"dividend": "sonstige", "distribution": "sonstige", "interest": "sonstige"}
"""Which pot each §20-typed transaction feeds — all three in the general
pot, because the aktien pot holds share *sales* alone (§20 Abs. 6 Satz 4
EStG) and Termingeschäfte their own. Share disposals (ticket 46) and
futures (ticket 28) will emit into theirs; the emitters know what they are,
never how the pots treat them (ADR-0013)."""


def year_report(engine: Engine, source: ReferenceRateSource, *, year: int) -> Section20Year:
    """The §20 answer for one Tax Year: the ledger's capital income reduced
    to Section 20 Events — withholding empty until tickets 43 and 47 state
    what was taken at source — then netted by the pure engine under the
    year's configured caps. Teilfreistellung stays zero here because no fund
    Instrument exists yet (ticket 44); once one does, a fund with no
    classification must block finalisation rather than silently assume a
    zero rate (CONTEXT.md, tickets 46/47)."""
    configured = {
        category: optional_value(engine, year=year, key=key)
        for category, key in LOSS_CAP_KEYS.items()
    }
    caps = {category: cap for category, cap in configured.items() if cap is not None}
    with lots.snapshot(engine) as connection:
        transaction_rows, leg_rows = lots_repository.ledger(connection)
        stance_rows = lots_repository.stance_rows(connection)
        instrument_rows = lots_repository.instrument_rows(connection)
    instruments = {row.id: row for row in instrument_rows}
    decisions_of = lots.grouped(stance_rows, "instrument_id")
    legs_of = lots.grouped(leg_rows, "transaction_id")

    events = []
    excluded = []
    awaiting = []
    for transaction in transaction_rows:
        if TAX_CONSEQUENCES[transaction.type].income != SECTION_20:
            continue
        if fx.event_date(transaction.occurred_at).year != year:
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
                awaiting.append(leg.id)
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

    return Section20Year(
        year=year,
        balances=net(events, year=year, caps=caps) if not awaiting else None,
        excluded=tuple(excluded),
        awaiting_valuation=tuple(awaiting),
    )
