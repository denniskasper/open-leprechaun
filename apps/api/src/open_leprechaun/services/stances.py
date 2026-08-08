"""What the application knows about Stances beyond storage (ADR-0012): the
Admin's standing position on an Instrument — what the Admin will do about the
thing, not what the thing provably is.

New Instruments arrive `unacknowledged` — no row, nobody has looked yet — and
wait in an inbox. This module answers the questions the rest of the roadmap
must ask it:

- what an acknowledged unsolicited inflow settles as, from the
  counter-performance answer (the transaction vocabulary's decision, made
  here so no route invents it);
- whether an inflow mints a Tax Lot, which the lot engine (ticket 19) reads;
- whether an Instrument may acquire a price source, which the price tickets
  (18, 45) must consult before attaching one.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.repositories import stances

STANCES = ("unacknowledged", "kept", "ignored", "dangerous")
"""The vocabulary; `unacknowledged` is the default and is never stored."""


def stance_of(engine: Engine, instrument_id: int, account_id: int) -> str:
    """The effective stance of one Instrument at one Account.

    A global `dangerous` verdict outranks any per-Account decision — a token
    whose approval drains a wallet is dangerous everywhere — and no decision
    at all is `unacknowledged`.
    """
    per_account = None
    for row in stances.list_stances(engine, instrument_id):
        if row.account_id is None:
            return row.stance
        if row.account_id == account_id:
            per_account = row.stance
    return per_account or "unacknowledged"


def inflow_mints_lot(stance: str) -> bool:
    """Whether an inflow under this stance mints a Tax Lot — the rule the lot
    engine (ticket 19) reads.

    Only `kept` does. Unacknowledged is deny by default: the failure mode of
    an unrecognised token is an item awaiting a decision, not a holding
    silently valued at zero. Ignored and dangerous stay visible as positions
    but never enter the cost basis.
    """
    return stance == "kept"


def settled_inflow_type(*, received_for_counter_performance: bool) -> str:
    """What keeping settles an unsolicited inflow as.

    Received for a counter-performance it is an `airdrop` — a Leistung, §22
    EStG income at market value on receipt. Received for nothing — the
    default answer — it is a `windfall`: no income, and no Anschaffung
    either, per the BMF letter of 10.05.2022 on virtual currencies.
    """
    return "airdrop" if received_for_counter_performance else "windfall"


def may_acquire_price_source(engine: Engine, instrument_id: int) -> bool:
    """Whether this Instrument may acquire a price source — the bar the price
    tickets (18, 45) must consult before attaching one.

    A dangerous Instrument never prices. An ignored one never prices either —
    unless the same Instrument is kept at some other Account, because dust
    ignored at one venue must not unprice the genuine holding at another.
    """
    rows = stances.list_stances(engine, instrument_id)
    if any(row.stance == "dangerous" for row in rows):
        return False
    if any(row.stance == "kept" for row in rows):
        return True
    return not any(row.stance == "ignored" for row in rows)


@dataclass(frozen=True)
class InboxItem:
    """One unacknowledged arrival: an Instrument at an Account, with the
    unsolicited inflows a keep decision would settle."""

    instrument_id: int
    family: str
    type: str
    symbol: str
    name: str
    chain: str | None
    contract_address: str | None
    isin: str | None
    account_id: int
    account_name: str
    platform_name: str
    unclassified_inflow_count: int
    unclassified_quantity: Decimal
    last_inflow_at: datetime


def inbox(engine: Engine) -> list[InboxItem]:
    """What waits on the Admin, newest arrival first."""
    return [
        InboxItem(
            instrument_id=row.instrument_id,
            family=row.family,
            type=row.type,
            symbol=row.symbol,
            name=row.name,
            chain=row.chain,
            contract_address=row.contract_address,
            isin=row.isin,
            account_id=row.account_id,
            account_name=row.account_name,
            platform_name=row.platform_name,
            unclassified_inflow_count=row.unclassified_inflow_count,
            unclassified_quantity=row.unclassified_quantity,
            last_inflow_at=row.last_inflow_at,
        )
        for row in stances.list_inbox(engine)
    ]
