"""A broker's harvest as the import framework's rows (ticket 48, ADR-0025).

This is where a broker's Normalized records become balanced legs — pure
translation, nothing read and nothing written; landing them is the sync
service's (services/connection_sync) and the import framework's.

Every Instrument is named by identity rather than by id: a security by its
ISIN, cash by its currency (ADR-0010). The import framework resolves each
against the ledger and mints what it has never seen — a security flagged for
review (ticket 44) — so a broker sync never refuses over an unknown paper,
the way a symbol-only exchange sync must.

A trade settles in the Depot's currency, so its cash leg is what the broker
actually debited or credited for the security; the amount as it was priced
travels beside the legs, never as one. Each fee is its own leg attached to
the leg it was charged against — the security for a cost of the trade, the
cash for a currency conversion — and inherits that leg's regime (ADR-0011).
A Normalized Position has no row here, and cannot be given one: the harvest
carries none.
"""

from decimal import Decimal

from open_leprechaun.ports.broker import (
    BrokerHarvest,
    NormalizedDividend,
    NormalizedSecurity,
    NormalizedSecurityTrade,
)
from open_leprechaun.repositories.transactions import OriginalAmount
from open_leprechaun.services import fx
from open_leprechaun.services.imports import (
    ImportCapitalIncome,
    ImportLeg,
    ImportRow,
    InstrumentSpec,
)


def import_rows(harvest: BrokerHarvest) -> list[ImportRow]:
    rows = [_trade(trade) for trade in harvest.trades]
    rows.extend(_dividend(dividend) for dividend in harvest.dividends)
    for movement in harvest.cash_movements:
        role = "in" if movement.direction == "in" else "out"
        rows.append(
            ImportRow(
                external_id=movement.external_id,
                type=f"transfer_{role}",
                occurred_at=movement.occurred_at,
                legs=(
                    ImportLeg(
                        role=role, quantity=movement.amount, instrument=_cash(movement.currency)
                    ),
                ),
            )
        )
    for fee in harvest.account_fees:
        rows.append(
            ImportRow(
                external_id=fee.external_id,
                type="fee",
                occurred_at=fee.occurred_at,
                legs=(ImportLeg(role="fee", quantity=fee.amount, instrument=_cash(fee.currency)),),
            )
        )
    return rows


def passed_over(harvest: BrokerHarvest) -> tuple[str, ...]:
    """What the venue stated that is no transaction, each a sentence for the
    Admin — dated by the Berlin day it happened on, oldest first."""
    return tuple(
        f"{fx.event_date(passed.occurred_at).isoformat()}: {passed.description}"
        for passed in sorted(harvest.passed_over, key=lambda passed: passed.occurred_at)
    )


def _cash(currency: str) -> InstrumentSpec:
    return InstrumentSpec(kind="cash", symbol=currency, name=currency)


def _security(security: NormalizedSecurity) -> InstrumentSpec:
    return InstrumentSpec(
        kind="security", symbol=security.symbol, name=security.name, isin=security.isin
    )


def _trade(trade: NormalizedSecurityTrade) -> ImportRow:
    security = ImportLeg(
        role="in" if trade.side == "buy" else "out",
        quantity=trade.quantity,
        instrument=_security(trade.security),
    )
    cash = ImportLeg(
        role="out" if trade.side == "buy" else "in",
        quantity=trade.settled_amount,
        instrument=_cash(trade.settlement_currency),
    )
    # What arrived first, like every trade in the ledger.
    legs = [security, cash] if trade.side == "buy" else [cash, security]
    position_of = {"security": legs.index(security), "cash": legs.index(cash)}
    legs.extend(
        ImportLeg(
            role="fee",
            quantity=fee.amount,
            instrument=_cash(fee.currency),
            charged_against=position_of[fee.charged_against],
        )
        for fee in trade.fees
    )
    original = None
    if trade.original is not None:
        original = OriginalAmount(
            amount=trade.original.amount,
            currency=trade.original.currency,
            rate=trade.original.fx_rate,
            # The broker converted when the trade filled; the date is that
            # instant's, by the clock every event date is read on.
            rate_date=fx.event_date(trade.occurred_at),
        )
    return ImportRow(
        external_id=trade.external_id,
        type="trade",
        occurred_at=trade.occurred_at,
        legs=tuple(legs),
        original_amount=original,
    )


def _dividend(dividend: NormalizedDividend) -> ImportRow:
    """The net that arrived as the one in-leg (ADR-0022), declaring beside
    it what the broker stated: the security that paid and whatever was
    withheld at source. A receipt is recorded as
    a dividend whatever paid it — a fund's Teilfreistellung follows the payer
    named here, not the type."""
    # A Quellensteuer is declared only where the broker named both the
    # amount and the country — one without the other cannot be judged.
    quellensteuer = (
        {
            "foreign_withholding": dividend.foreign_withholding,
            "source_country": dividend.source_country,
        }
        if dividend.foreign_withholding and dividend.source_country
        else {}
    )
    declared = ImportCapitalIncome(
        paying_instrument=None if dividend.security is None else _security(dividend.security),
        kapitalertragsteuer=dividend.kapitalertragsteuer or Decimal(0),
        solidarity_surcharge=dividend.solidarity_surcharge or Decimal(0),
        church_tax=dividend.church_tax or Decimal(0),
        **quellensteuer,
    )
    if declared == ImportCapitalIncome():
        # Nothing stated beyond the net: no declaration, rather than an
        # empty one that reads as "nothing was withheld".
        declared = None
    note = None
    if dividend.gross_amount is not None and dividend.foreign_withholding is None:
        # The gross is the one figure the Admin needs to state what was
        # withheld, so it is kept where the event is read.
        note = (
            f"The venue states a gross of {dividend.gross_amount:f}"
            f" {dividend.gross_currency} before anything withheld, and not what"
            " was withheld."
        )
    return ImportRow(
        external_id=dividend.external_id,
        type=dividend.kind,
        occurred_at=dividend.occurred_at,
        note=note,
        legs=(ImportLeg(role="in", quantity=dividend.amount, instrument=_cash(dividend.currency)),),
        capital_income=declared,
    )
