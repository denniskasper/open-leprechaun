"""Dividends, distributions and interest (ticket 47): income from securities
and cash as §20 capital income, recorded gross with every tax already taken
out of it.

The ledger's in-leg is the net that arrived; the Transaction's capital-income
declaration states what the payer's statement says beyond it — the
Quellensteuer with its source country, and the German tax withheld at source
split into Kapitalertragsteuer, Solidaritätszuschlag and church tax. The
gross is the net plus everything withheld, every component in the received
leg's own Instrument and converted by the one valuation rule at the event
date (ADR-0017). A receipt with no declaration had nothing withheld: its
gross is its net.

What the producer knows ends at the event boundary (ADR-0013): each receipt
states the pot it feeds — all three types are general capital income, the
aktien pot holding share *sales* alone (§20 Abs. 6 Satz 4 EStG) — and, where
a fund paid, the Teilfreistellung rate that fund's category selects from the
per-year statutory store (§20 InvStG). The engine (services/section20)
reduces each receipt to one Section 20 Event and alone exempts, nets, judges
creditability and rates — no tax is computed here.

Whether the receipt is settled or still to declare is the Depot's fact, not
the receipt's: income in an Account whose effective withholding behaviour is
`at_source` (ticket 43) was taxed before it arrived; everything else must be
declared.

A distribution that names no paying fund, or names one with no
Teilfreistellung classification, refuses by name rather than assuming a zero
exemption (ticket 44) — the Admin's to settle, unlike a valuation nothing can
state yet, which is carried explicitly as awaiting, never guessed at.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import partial

from sqlalchemy import Engine, Row

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import capital_income as capital_income_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.repositories.instruments import FUND_TYPES
from open_leprechaun.repositories.transactions import CapitalIncome
from open_leprechaun.services import fx, lots
from open_leprechaun.services.security_disposals import (
    UnclassifiedSecurityError,
    partial_exemption_rate,
)
from open_leprechaun.services.stances import income_excluding_stance
from open_leprechaun.services.tax_treatment import SECTION_20, TAX_CONSEQUENCES

__all__ = ["CATEGORY", "ExcludedEvent", "IncomeReceipt", "Receipts", "receipts_through"]

CATEGORY = "sonstige"
"""Where every dividend, distribution and interest payment lands (§20 Abs. 1
Nr. 1, 3 und 7 EStG): the general pot — the aktien pot holds share *sales*
alone (§20 Abs. 6 Satz 4 EStG)."""


@dataclass(frozen=True)
class IncomeReceipt:
    """One §20-typed in-leg with what was taken out of it before it arrived,
    every figure in EUR at the event date's rate — None while a valuation
    awaits, never a guess. `gross_eur` is the net plus everything withheld;
    `settled_at_source` says whether the Depot that received it withholds
    German tax (ticket 43) or leaves the income to be declared."""

    leg_id: int
    type: str
    account_id: int
    instrument_id: int
    paying_instrument_id: int | None
    received_at: datetime
    tax_year: int
    category: str
    # The paying fund's per-year Teilfreistellung rate (§20 InvStG) — zero
    # where no fund paid.
    exemption_rate: Decimal
    settled_at_source: bool
    source_country: str | None
    net_eur: Decimal | None
    foreign_withholding_eur: Decimal | None
    kapitalertragsteuer_eur: Decimal | None
    solidarity_surcharge_eur: Decimal | None
    church_tax_eur: Decimal | None
    gross_eur: Decimal | None


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
class Receipts:
    """Everything the ledger's §20-typed income says up to a year's end:
    what counts, and what stance kept out of the target year itself — a
    prior year's exclusion is that year's own report's to name."""

    counted: tuple[IncomeReceipt, ...]
    excluded: tuple[ExcludedEvent, ...]


_NOTHING_DECLARED = CapitalIncome()


def receipts_through(engine: Engine, source: ReferenceRateSource, *, through_year: int) -> Receipts:
    """Every dividend, distribution and interest receipt up to the end of
    the Tax Year — earlier years too, because the engine's carryforward
    chain nets each of them."""
    with lots.snapshot(engine) as connection:
        transaction_rows, leg_rows = lots_repository.ledger(connection)
        stance_rows = lots_repository.stance_rows(connection)
        instrument_rows = lots_repository.instrument_rows(connection)
        declaration_rows = capital_income_repository.declaration_rows(connection)
        withholding_accounts = capital_income_repository.withholding_accounts(connection)
    instruments = {row.id: row for row in instrument_rows}
    decisions_of = lots.grouped(stance_rows, "instrument_id")
    legs_of = lots.grouped(leg_rows, "transaction_id")
    declared_of = {row.transaction_id: row for row in declaration_rows}

    counted = []
    excluded = []
    for transaction in transaction_rows:
        if TAX_CONSEQUENCES[transaction.type].income != SECTION_20:
            continue
        tax_year = fx.event_date(transaction.occurred_at).year
        if tax_year > through_year:
            continue
        declared = declared_of.get(transaction.id, _NOTHING_DECLARED)
        for leg in legs_of.get(transaction.id, []):
            if leg.role != "in":
                continue
            stance = income_excluding_stance(
                instrument=instruments[leg.instrument_id],
                decisions=decisions_of.get(leg.instrument_id, ()),
                account_id=leg.account_id,
            )
            if stance is not None:
                if tax_year == through_year:
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
            payer = (
                instruments[declared.paying_instrument_id]
                if declared.paying_instrument_id is not None
                else None
            )

            valued = partial(
                fx.value_eur,
                engine,
                source,
                instrument=instruments[leg.instrument_id],
                at=transaction.occurred_at,
            )
            withheld = (
                declared.foreign_withholding
                + declared.kapitalertragsteuer
                + declared.solidarity_surcharge
                + declared.church_tax
            )
            counted.append(
                IncomeReceipt(
                    leg_id=leg.id,
                    type=transaction.type,
                    account_id=leg.account_id,
                    instrument_id=leg.instrument_id,
                    paying_instrument_id=declared.paying_instrument_id,
                    received_at=transaction.occurred_at,
                    tax_year=tax_year,
                    category=CATEGORY,
                    exemption_rate=_exemption_rate(engine, transaction, payer, year=tax_year),
                    settled_at_source=leg.account_id in withholding_accounts,
                    source_country=declared.source_country,
                    net_eur=valued(quantity=leg.quantity),
                    foreign_withholding_eur=valued(quantity=declared.foreign_withholding),
                    kapitalertragsteuer_eur=valued(quantity=declared.kapitalertragsteuer),
                    solidarity_surcharge_eur=valued(quantity=declared.solidarity_surcharge),
                    church_tax_eur=valued(quantity=declared.church_tax),
                    gross_eur=valued(quantity=leg.quantity + withheld),
                )
            )
    return Receipts(counted=tuple(counted), excluded=tuple(excluded))


def _exemption_rate(engine: Engine, transaction: Row, payer: Row | None, *, year: int) -> Decimal:
    """The Teilfreistellung the receipt's year grants it: the paying fund's
    category rate (§20 InvStG) — whatever type the payout was recorded under,
    because the exemption follows the payer, not the label — and zero where
    no fund paid. A distribution is a fund's by definition: one naming no
    payer refuses, as an unclassified fund does, rather than entering its pot
    unexempted."""
    paid_by_fund = payer is not None and payer.type in FUND_TYPES
    if transaction.type == "distribution" and not paid_by_fund:
        on = fx.event_date(transaction.occurred_at).isoformat()
        raise UnclassifiedSecurityError(
            f"The distribution of {on} names no paying fund — name it on the"
            " Transaction before its exempt share can be stated."
        )
    if payer is None or not paid_by_fund:
        return Decimal(0)
    if payer.fund_category is None:
        raise UnclassifiedSecurityError(
            f"The fund {payer.symbol} carries no Teilfreistellung classification —"
            " classify it before its distribution can state the exempt share."
        )
    return partial_exemption_rate(engine, payer, year=year)
