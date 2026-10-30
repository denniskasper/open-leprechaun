"""What the application knows about Platforms beyond storage: the overview
that hands the UI every Platform with its Accounts nested under it, because an
Account never appears anywhere without its location — and the rule for taking
one back, which is refused in words the Admin can act on."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.repositories import platforms
from open_leprechaun.repositories.platforms import Refusal


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
class AllowanceUsed:
    """How much of the Sparerpauschbetrag the Platform's exemption order used
    in one Tax Year, as its annual tax certificate states it (issue 28)."""

    year: int
    amount_eur: Decimal


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
    # Ordered by year; only ever on a broker or a bank, whatever its
    # withholding behaviour now is.
    allowance_used: tuple[AllowanceUsed, ...]


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
    used_at: dict[int, list[AllowanceUsed]] = {}
    for row in platforms.list_allowance_used(engine):
        used_at.setdefault(row.platform_id, []).append(
            AllowanceUsed(year=row.year, amount_eur=row.amount_eur)
        )
    return [
        PlatformOverview(
            id=row.id,
            name=row.name,
            kind=row.kind,
            withholding=row.withholding,
            exemption_order_eur=row.exemption_order_eur,
            accounts=tuple(accounts_of.get(row.id, [])),
            allowance_used=tuple(used_at.get(row.id, [])),
        )
        for row in platforms.list_platforms(engine)
    ]


@dataclass(frozen=True)
class Refused:
    """A removal the rule refused: nothing was deleted, and the reason names
    what is in the way so the Admin knows what to do next."""

    reason: str


def _named(noun: str, names: tuple[str, ...]) -> str:
    """ "the Account 'Main'", "the Accounts 'Main' and 'Savings'"."""
    quoted = [f"'{name}'" for name in names]
    listed = quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} and {quoted[-1]}"
    return f"the {noun}{'' if len(quoted) == 1 else 's'} {listed}"


def remove_platform(engine: Engine, platform_id: int) -> Refused | Refusal | None:
    """A Platform may be removed only while it holds no Account, no
    Connection and no allowance used at source — removing one never takes
    anything else with it, and never silently changes a past year's tax. None
    means it is gone."""
    held = platforms.delete_platform(engine, platform_id)
    if not isinstance(held, platforms.PlatformHolders):
        return held
    in_the_way = [
        _named(noun, names)
        for noun, names in (("Account", held.accounts), ("Connection", held.connections))
        if names
    ]
    # Named without a count or a year: the Admin clears them one by one in the
    # withholding settings, where they are listed.
    if held.holds_allowance_used:
        in_the_way.append("an allowance used at source")
    held_count = len(held.accounts) + len(held.connections) + int(held.holds_allowance_used)
    them = "it" if held_count == 1 else "them"
    return Refused(f"This Platform still holds {' and '.join(in_the_way)} — remove {them} first.")


def remove_account(engine: Engine, account_id: int) -> Refused | Refusal | None:
    """An Account may be removed only while nothing was ever recorded in it
    and no Connection is paired with it. History never goes, so an Account
    that has any stays for good; a pairing has to be released by the Admin,
    because a silently unpaired Connection would keep syncing and land
    nothing. Where both hold it, only the history is named: unpairing would
    not make it removable. None means it is gone."""
    held = platforms.delete_account(engine, account_id)
    if not isinstance(held, platforms.AccountHolders):
        return held
    if held.recorded:
        return Refused("This Account has recorded history, so it stays for good.")
    paired = " and ".join(f"the Connection '{label}' ({kind})" for label, kind in held.pairings)
    return Refused(f"This Account is paired with {paired} — unpair it first.")
