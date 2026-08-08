"""Each transaction type's tax consequence, documented in one place — which
the tax engines alone will read (tickets 21, 22, 26). Nothing else imports
this module, and a test holds it to that, so a classification cannot drift
between the ledger and the report.

Two rules sit above the table:

- A fee leg's treatment is read from the regime of the leg it was charged
  against, never from the transaction's type (ADR-0011) — which is what makes
  a currency-conversion fee a cost of acquiring that currency rather than a
  transaction cost of the trade it enabled. A fee with no attachment is a
  bare cost under its transaction's own regime.
- Whether moving an Instrument is itself a disposal is answered by
  services/instruments.movement_is_disposal: the EUR numéraire moves freely,
  everything else is an ordinary asset.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class Inflow(Enum):
    """What an in-leg means for cost basis."""

    # A purchase: the lot's basis is what left, plus attached fees.
    mints_lot_at_cost = "mints_lot_at_cost"
    # Income: valued at market value on receipt, minting a lot at that basis.
    income_at_market_value = "income_at_market_value"
    # No lot and no invented basis until matching (16), an Opening Balance
    # (15) or a Stance decision (14) settles what the inflow was — an
    # unclassified inflow is never assumed to be a purchase.
    no_lot_until_classified = "no_lot_until_classified"
    # Kept, but received for nothing: no income — no Leistung, so nothing
    # under §22 — and no Anschaffungsvorgang either (BMF letter of
    # 10.05.2022 on virtual currencies). The lot is minted at zero basis,
    # marked as acquired without consideration, so the holding stays visible
    # while ticket 21 keeps its disposal out of §23.
    no_acquisition = "no_acquisition"
    # The type records no in-leg.
    none_expected = "none_expected"


class Outflow(Enum):
    """What an out-leg means for disposal."""

    # A disposal, consuming lots FIFO within the Account and Instrument.
    disposal = "disposal"
    # Not a disposal until matched to the Admin's own deposit; unmatched it
    # stays visible as unmatched, never quietly a sale.
    awaiting_match = "awaiting_match"
    # The type records no out-leg.
    none_expected = "none_expected"


@dataclass(frozen=True)
class TaxConsequence:
    inflow: Inflow
    outflow: Outflow
    # The statute the income falls under, where the type is income at all.
    income: str | None = None


TAX_CONSEQUENCES: Mapping[str, TaxConsequence] = {
    # Out legs dispose of what left; in legs mint lots at cost. Which regime
    # — §23 private sale or §20 capital income — follows from the Instrument's
    # family, not from the type.
    "trade": TaxConsequence(Inflow.mints_lot_at_cost, Outflow.disposal),
    "transfer_in": TaxConsequence(Inflow.no_lot_until_classified, Outflow.none_expected),
    "transfer_out": TaxConsequence(Inflow.none_expected, Outflow.awaiting_match),
    "spend": TaxConsequence(Inflow.none_expected, Outflow.disposal),
    # §22 EStG sonstige Einkünfte: valued on receipt, pooled under the annual
    # Freigrenze (ticket 22).
    "staking_reward": TaxConsequence(
        Inflow.income_at_market_value, Outflow.none_expected, income="§22 EStG"
    ),
    "lending_interest": TaxConsequence(
        Inflow.income_at_market_value, Outflow.none_expected, income="§22 EStG"
    ),
    "mining_reward": TaxConsequence(
        Inflow.income_at_market_value, Outflow.none_expected, income="§22 EStG"
    ),
    "airdrop": TaxConsequence(
        Inflow.income_at_market_value, Outflow.none_expected, income="§22 EStG"
    ),
    # An unsolicited inflow kept without a counter-performance — what a
    # Stance decision (ticket 14) settles it as when the answer is no.
    "windfall": TaxConsequence(Inflow.no_acquisition, Outflow.none_expected),
    # §20 EStG capital income: each becomes a Section 20 Event carrying its
    # category (ticket 26); withholding at source is ticket 43's.
    "dividend": TaxConsequence(
        Inflow.income_at_market_value, Outflow.none_expected, income="§20 EStG"
    ),
    "distribution": TaxConsequence(
        Inflow.income_at_market_value, Outflow.none_expected, income="§20 EStG"
    ),
    "interest": TaxConsequence(
        Inflow.income_at_market_value, Outflow.none_expected, income="§20 EStG"
    ),
    # A bare cost; its deductibility follows the regime of what it was
    # charged against, and a standalone fee has nothing to enable.
    "fee": TaxConsequence(Inflow.none_expected, Outflow.none_expected),
}
