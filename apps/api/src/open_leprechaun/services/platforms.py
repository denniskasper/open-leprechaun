"""What the application knows about Platforms beyond storage: the overview
that hands the UI every Platform with its Accounts nested under it, because an
Account never appears anywhere without its location."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.repositories import platforms


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    chain: str | None
    external_reference: str | None
    access_software: str | None
    # The one ingestion source that may write here (ticket 31); None until an
    # import declares itself or the Admin declares one.
    authoritative_source: str | None
    # This Account's exception to its Platform's withholding behaviour
    # (ticket 43); None means the Platform's word stands.
    withholding_override: str | None
    base_currency: str | None


@dataclass(frozen=True)
class PlatformOverview:
    id: int
    name: str
    kind: str
    # How income at this broker is treated at source (ticket 43): 'at_source',
    # 'none', or None while nothing has been declared. Always None outside
    # kind 'broker'; the exemption order may only stand with 'at_source'.
    withholding: str | None
    exemption_order_eur: Decimal | None
    accounts: tuple[Account, ...]


def overview(engine: Engine) -> list[PlatformOverview]:
    accounts_of: dict[int, list[Account]] = {}
    for row in platforms.list_accounts(engine):
        accounts_of.setdefault(row.platform_id, []).append(
            Account(
                id=row.id,
                name=row.name,
                chain=row.chain,
                external_reference=row.external_reference,
                access_software=row.access_software,
                authoritative_source=row.authoritative_source,
                withholding_override=row.withholding_override,
                base_currency=row.base_currency,
            )
        )
    return [
        PlatformOverview(
            id=row.id,
            name=row.name,
            kind=row.kind,
            withholding=row.withholding,
            exemption_order_eur=row.exemption_order_eur,
            accounts=tuple(accounts_of.get(row.id, [])),
        )
        for row in platforms.list_platforms(engine)
    ]
