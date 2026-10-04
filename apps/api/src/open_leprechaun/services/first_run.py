"""The first-run checklist (ticket 58): the walk from an empty database to a
first tax report, in the order the Admin takes it.

Every item is derived, on each read, from what the database holds — an Admin
row, an Account, a Connection, a recorded reconciliation, a Tax Year free of
pre-flight blockers, a report. Nothing is stored for the checklist and
nothing about it can be dismissed: an item is done because the thing it asks
for exists, and undone again the moment it no longer does.

An optional item is one the walk can finish without. Two-factor is opt-in
(ADR-0005), and a ledger no Connection states a balance for has nothing to
reconcile against.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Engine

from open_leprechaun.repositories import first_run as repository
from open_leprechaun.services import preflight, reconciliation
from open_leprechaun.services.reconciliation import Adapters

Key = Literal[
    "password",
    "two_factor",
    "platforms_and_accounts",
    "connect_or_import",
    "reconcile",
    "blockers",
    "report",
]


@dataclass(frozen=True)
class Item:
    """One step of the walk: whether what it asks for exists, a sentence
    saying what that was read from, and the screen that completes it."""

    key: Key
    done: bool
    optional: bool
    detail: str
    resolve_path: str


@dataclass(frozen=True)
class Checklist:
    items: tuple[Item, ...]

    @property
    def complete(self) -> bool:
        """Every step the walk cannot finish without is done."""
        return all(item.done for item in self.items if not item.optional)


def checklist(engine: Engine, adapters: Adapters) -> Checklist:
    tally = repository.tally(engine)
    return Checklist(
        items=(
            _password(engine),
            _two_factor(),
            _platforms_and_accounts(tally.platforms, tally.accounts),
            _connect_or_import(tally.connections, tally.import_batches, tally.transactions),
            _reconcile(engine, adapters),
            _blockers(engine),
            _report(tally.reports),
        )
    )


def _password(engine: Engine) -> Item:
    done = repository.admin_exists(engine)
    return Item(
        key="password",
        done=done,
        optional=False,
        detail="The Admin password is set."
        if done
        else "No Admin password is set — whoever reaches this instance first can claim it.",
        resolve_path="/setup",
    )


def _two_factor() -> Item:
    # Ticket 08 lands enrolment and, with it, the row this reads. Until then
    # no instance has a second factor, which is exactly what the item says.
    return Item(
        key="two_factor",
        done=False,
        optional=True,
        detail="Two-factor is off — this version cannot enrol a second factor yet.",
        resolve_path="/settings/security",
    )


def _platforms_and_accounts(platforms: int, accounts: int) -> Item:
    if accounts:
        detail = f"{_count(platforms, 'Platform')} and {_count(accounts, 'Account')} exist."
    elif platforms:
        detail = (
            f"{_count(platforms, 'Platform')} but no Account — add an Account under a"
            " Platform; Transactions are recorded against Accounts."
        )
    else:
        detail = "No Platform yet — add each place that holds value, then an Account under it."
    return Item(
        key="platforms_and_accounts",
        done=accounts > 0,
        optional=False,
        detail=detail,
        resolve_path="/settings/platforms",
    )


def _connect_or_import(connections: int, import_batches: int, transactions: int) -> Item:
    held = [
        _count(count, noun)
        for count, noun in (
            (connections, "Connection"),
            (import_batches, "Import Batch"),
            (transactions, "Transaction"),
        )
        if count
    ]
    return Item(
        key="connect_or_import",
        done=bool(held),
        optional=False,
        detail=f"History has a way in: {', '.join(held)}."
        if held
        else "No history yet — import a file, or add a Connection and sync it.",
        resolve_path="/imports",
    )


def _reconcile(engine: Engine, adapters: Adapters) -> Item:
    """Done once every Connection that can be reconciled has been, its last
    run leaving nothing open. A Connection whose venue states no balances
    has nothing to compare and asks for nothing."""
    connections = [
        row
        for row in repository.reconciliations(engine)
        if reconciliation.states_positions(adapters, row.venue)
    ]
    never = [row.label for row in connections if row.reconciled_at is None]
    open_ = [
        row.label
        for row in connections
        if row.reconciled_at is not None and (row.gaps or row.failed_kinds)
    ]
    if not connections:
        detail = (
            "No Connection states what its venue holds, so there is no balance to compare"
            " against — a ledger fed by imports alone has nothing to reconcile."
        )
    elif never:
        detail = f"Never reconciled: {', '.join(never)}."
    elif open_:
        detail = (
            f"The last reconciliation left differences open: {', '.join(open_)}."
            " Import the missing history or record an Opening Balance, then reconcile again."
        )
    else:
        detail = (
            f"{_count(len(connections), 'Connection')} reconciled, the venue and the"
            " ledger agreeing when last compared."
        )
    return Item(
        key="reconcile",
        done=bool(connections) and not never and not open_,
        optional=not connections,
        detail=detail,
        resolve_path="/settings/connections",
    )


def _blockers(engine: Engine) -> Item:
    """Done once one Tax Year with activity has nothing standing in the way
    of its report — the walk ends at a first report, not at every year's."""
    blocked = {
        year: len(preflight.blockers(engine, year=year))
        for year in repository.activity_years(engine)
    }
    clear = [str(year) for year, count in blocked.items() if not count]
    if not blocked:
        detail = "No Tax Year has activity yet — blockers are judged once the ledger has history."
    elif clear:
        detail = f"Nothing stands in the way of a report for {', '.join(clear)}."
    else:
        years = ", ".join(f"{year} ({_count(count, 'blocker')})" for year, count in blocked.items())
        detail = f"Every Tax Year with activity has blockers open: {years}."
    return Item(
        key="blockers",
        done=bool(clear),
        optional=False,
        detail=detail,
        resolve_path="/tax/overview",
    )


def _report(reports: int) -> Item:
    return Item(
        key="report",
        done=reports > 0,
        optional=False,
        detail=f"{_count(reports, 'report')} generated."
        if reports
        else "No report yet — generate one for a Tax Year.",
        resolve_path="/tax/overview",
    )


def _count(count: int, noun: str) -> str:
    plural = f"{noun}es" if noun.endswith("ch") else f"{noun}s"
    return f"{count} {noun if count == 1 else plural}"
