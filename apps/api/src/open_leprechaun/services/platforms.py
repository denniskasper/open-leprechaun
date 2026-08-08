"""What the application knows about Platforms beyond storage: the overview
that hands the UI every Platform with its Accounts nested under it, because an
Account never appears anywhere without its location."""

from dataclasses import dataclass

from sqlalchemy import Engine

from open_leprechaun.repositories import platforms


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    chain: str | None
    external_reference: str | None
    access_software: str | None


@dataclass(frozen=True)
class PlatformOverview:
    id: int
    name: str
    kind: str
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
            )
        )
    return [
        PlatformOverview(
            id=row.id,
            name=row.name,
            kind=row.kind,
            accounts=tuple(accounts_of.get(row.id, [])),
        )
        for row in platforms.list_platforms(engine)
    ]
