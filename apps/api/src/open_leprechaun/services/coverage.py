"""Coverage warnings (ticket 40, ADR-0008): a venue whose history window
opens later than the earliest activity recorded elsewhere is a silent gap —
"no trades found" would pass for "no trades exist" — so the dashboard names
it and points at the import path that closes it.

An Account's coverage starts where the evidence says it does: the earliest
instant a bounded sync window claimed (per kind; where kinds differ the
latest window is the honest single date, because only then is every kind
covered), pulled earlier by any activity already recorded in the Account —
history imported from a file is coverage no matter what claimed it.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, Row

from open_leprechaun.repositories import coverage as repository


@dataclass(frozen=True)
class CoverageWarning:
    """One venue account whose coverage starts too late, named in the words
    the Admin knows it by."""

    connection_id: int
    connection_label: str
    venue: str
    platform_name: str
    account_id: int
    account_name: str
    coverage_starts_at: datetime
    earliest_elsewhere_at: datetime


def warnings(engine: Engine) -> list[CoverageWarning]:
    """Every paired Account whose coverage begins after the earliest activity
    recorded in any other Account — ordered as the pairings are, so the list
    is stable across refreshes."""
    earliest = repository.earliest_activity_by_account(engine)
    accounts: dict[int, Row] = {}
    for row in repository.covered_pairings(engine):
        held = accounts.get(row.account_id)
        # Several kinds land in one Account: full coverage begins only where
        # the most limited window does, so the latest claim wins.
        if held is None or row.covered_from > held.covered_from:
            accounts[row.account_id] = row
    results = []
    for account_id, row in accounts.items():
        coverage_starts_at = row.covered_from
        recorded = earliest.get(account_id)
        if recorded is not None and recorded < coverage_starts_at:
            coverage_starts_at = recorded
        elsewhere = min(
            (at for other_id, at in earliest.items() if other_id != account_id),
            default=None,
        )
        if elsewhere is not None and elsewhere < coverage_starts_at:
            results.append(
                CoverageWarning(
                    connection_id=row.connection_id,
                    connection_label=row.connection_label,
                    venue=row.venue,
                    platform_name=row.platform_name,
                    account_id=account_id,
                    account_name=row.account_name,
                    coverage_starts_at=coverage_starts_at,
                    earliest_elsewhere_at=elsewhere,
                )
            )
    return results
