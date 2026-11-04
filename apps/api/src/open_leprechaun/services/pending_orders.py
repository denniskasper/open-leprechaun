"""What each Depot's broker last said it holds open (Pending Orders): read
for Holdings, which shows them as notes beside the positions they concern.

Nothing here derives anything. A Pending Order is an observation, recorded
where the broker was asked — at a sync or a reconciliation — and stated as of
then; it never reaches the ledger, a lot or a tax figure.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.repositories import pending_orders as repository


@dataclass(frozen=True)
class PendingOrder:
    external_id: str
    created_at: datetime
    isin: str
    symbol: str
    name: str
    side: str
    order_type: str
    currency: str
    quantity: Decimal | None
    value: Decimal | None
    limit_price: Decimal | None
    stop_price: Decimal | None


@dataclass(frozen=True)
class Observation:
    """One Depot's last answer: its open orders and the cash held back for
    them as of `as_of` — or, beside an `error`, the sentence that says why
    they could not be read."""

    account_id: int
    as_of: datetime
    error: str | None
    reserved_cash: Decimal | None
    reserved_currency: str | None
    orders: tuple[PendingOrder, ...]


def observed(engine: Engine) -> list[Observation]:
    by_account: dict[int, list[PendingOrder]] = {}
    for row in repository.orders(engine):
        fields = row._asdict()
        account_id = fields.pop("account_id")
        by_account.setdefault(account_id, []).append(PendingOrder(**fields))
    return [
        Observation(
            account_id=row.account_id,
            as_of=row.as_of,
            error=row.error,
            reserved_cash=row.reserved_cash,
            reserved_currency=row.reserved_currency,
            orders=tuple(by_account.get(row.account_id, ())),
        )
        for row in repository.observations(engine)
    ]
