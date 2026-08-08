"""The §22 EStG income engine (ticket 22): Sonstige Einkünfte from crypto —
staking rewards, lending interest, mining and qualifying airdrops — derived
from the ledger, never maintained beside it.

Income is a Leistung valued at market value on receipt (§22 Nr. 3 EStG), and
the same in-leg simultaneously mints a Tax Lot at that basis (services/lots,
`basis_source = market_value`): one event, one valuation rule — the one the
reference-rate universe states (ADR-0017, fx.value_eur) — so income and cost
basis can never disagree. Classification follows the transaction type alone,
and the report names every event it pooled, wearing that type.

Three rules sit on top:

- **Freigrenze** (§22 Nr. 3 Satz 2 EStG): all qualifying income of a year
  pools under one limit, read per year from the statutory store (ticket 09),
  never from a constant. The statute says *weniger als*: below the limit the
  whole amount is free, at the limit it is already fully taxable — and the
  headroom or overshoot is stated either way. A year whose limit is unset
  refuses to compute rather than assuming one.
- **A taxable amount, never a euro owed** (ADR-0007): Sonstige Einkünfte are
  taxed at the recipient's personal marginal rate, which this ledger cannot
  know — so the report states what is taxable and stops there.
- **Tax Year**: income is bucketed by the Europe/Berlin local date of its
  instant — the same clock as every reference-rate lookup — while the
  instant itself stays absolute.

An event pools exactly when its in-leg mints (services/stances): a non-kept
position pools nothing — unacknowledged waits visibly in the inbox rather
than being valued silently, and an ignored or dangerous one never enters —
while numéraire income, which has no lot to mint, is its own value. What
stance keeps out of the pool the report still names as excluded, wearing
that stance, so a tax-free verdict can never silently hide a reward waiting
on a decision. A value needing a crypto price waits for ticket 18: such an
event is carried explicitly as awaiting valuation, never guessed at, and
while any pooled event awaits one the year states no total and no verdict.

Delegation stands entirely outside this module: an informational marker per
Account and Instrument (services/delegation), never a tax input.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.services import fx, lots
from open_leprechaun.services.stances import effective_stance, inflow_mints_lot
from open_leprechaun.services.statutory import StatutoryValueUnsetError, required_value
from open_leprechaun.services.tax_treatment import SECTION_22, TAX_CONSEQUENCES

__all__ = ["EXEMPTION_LIMIT_KEY", "StatutoryValueUnsetError", "year_report"]

EXEMPTION_LIMIT_KEY = "other_income_exemption_limit"
"""The §22 Nr. 3 Satz 2 EStG Freigrenze in the statutory vocabulary."""


@dataclass(frozen=True)
class IncomeEvent:
    """One pooled receipt, named by the transaction type that classified it.
    `market_value_eur` is None while the value awaits a crypto price
    (ticket 18)."""

    leg_id: int
    type: str
    account_id: int
    instrument_id: int
    received_at: datetime
    tax_year: int
    quantity: Decimal
    market_value_eur: Decimal | None


@dataclass(frozen=True)
class FreigrenzeVerdict:
    """The §22 Nr. 3 Satz 2 EStG all-or-nothing answer for one year: below
    the limit the whole income is free and the headroom is stated; at or
    above it — *weniger als*, so exactly the limit already counts — the whole
    amount is taxable and the overshoot is stated. Always an amount, never a
    euro of tax owed: the marginal rate is the Admin's, not the ledger's."""

    limit_eur: Decimal
    total_income_eur: Decimal
    tax_free: bool
    headroom_eur: Decimal | None
    overshoot_eur: Decimal | None
    taxable_income_eur: Decimal


@dataclass(frozen=True)
class ExcludedEvent:
    """One §22-typed receipt the pool refused, named so the verdict beside
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
class Section22Year:
    """Every pooled income event of one Tax Year, with what stance kept out
    stated beside it. While a pooled event awaits valuation the year states
    no total and no verdict, and names the events it waits on."""

    year: int
    incomes: tuple[IncomeEvent, ...]
    excluded: tuple[ExcludedEvent, ...]
    total_income_eur: Decimal | None
    awaiting_valuation: tuple[int, ...]
    freigrenze: FreigrenzeVerdict | None


def year_report(engine: Engine, source: ReferenceRateSource, *, year: int) -> Section22Year:
    """The §22 answer for one Tax Year — only this year's events are valued,
    so another year's income costs no rate lookup and cannot fail over one."""
    limit = required_value(
        engine, year=year, key=EXEMPTION_LIMIT_KEY, statute="§22 Nr. 3 Satz 2 EStG"
    )
    with lots.snapshot(engine) as connection:
        transaction_rows, leg_rows = lots_repository.ledger(connection)
        stance_rows = lots_repository.stance_rows(connection)
        instrument_rows = lots_repository.instrument_rows(connection)
    instruments = {row.id: row for row in instrument_rows}
    decisions_of = lots.grouped(stance_rows, "instrument_id")
    legs_of = lots.grouped(leg_rows, "transaction_id")

    incomes = []
    excluded = []
    for transaction in transaction_rows:
        if TAX_CONSEQUENCES[transaction.type].income != SECTION_22:
            continue
        if fx.event_date(transaction.occurred_at).year != year:
            continue
        for leg in legs_of.get(transaction.id, []):
            if leg.role != "in":
                continue
            stance = _excluding_stance(leg, instruments, decisions_of)
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
            incomes.append(
                IncomeEvent(
                    leg_id=leg.id,
                    type=transaction.type,
                    account_id=leg.account_id,
                    instrument_id=leg.instrument_id,
                    received_at=transaction.occurred_at,
                    tax_year=year,
                    quantity=leg.quantity,
                    market_value_eur=fx.value_eur(
                        engine,
                        source,
                        instrument=instruments[leg.instrument_id],
                        quantity=leg.quantity,
                        at=transaction.occurred_at,
                    ),
                )
            )

    awaiting = tuple(event.leg_id for event in incomes if event.market_value_eur is None)
    total = sum((event.market_value_eur for event in incomes), Decimal(0)) if not awaiting else None
    return Section22Year(
        year=year,
        incomes=tuple(incomes),
        excluded=tuple(excluded),
        total_income_eur=total,
        awaiting_valuation=awaiting,
        freigrenze=_verdict(limit, total) if total is not None else None,
    )


def _excluding_stance(
    leg: Row, instruments: dict[int, Row], decisions_of: dict[int, list[Row]]
) -> str | None:
    """The stance keeping this in-leg's income out of the pool — None when it
    pools. Income pools exactly when the leg mints its Tax Lot
    (services/stances), because income and basis are two sides of one event;
    the numéraire mints no lot only because it has no basis of its own, so
    its income is its quantity and pools unconditionally."""
    instrument = instruments[leg.instrument_id]
    if instrument.is_numeraire:
        return None
    stance = effective_stance(decisions_of.get(leg.instrument_id, ()), leg.account_id)
    return None if inflow_mints_lot(stance) else stance


def _verdict(limit: Decimal, total: Decimal) -> FreigrenzeVerdict:
    tax_free = total < limit
    return FreigrenzeVerdict(
        limit_eur=limit,
        total_income_eur=total,
        tax_free=tax_free,
        headroom_eur=limit - total if tax_free else None,
        overshoot_eur=total - limit if not tax_free else None,
        taxable_income_eur=Decimal(0) if tax_free else total,
    )
