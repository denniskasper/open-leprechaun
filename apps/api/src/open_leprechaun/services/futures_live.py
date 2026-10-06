"""Live Positions (CONTEXT.md): what each venue states about its open
futures positions at the moment it is asked, repeated for the Futures screen
and never stored. Nothing here writes: the ledger's positions come from fills
alone (ADR-0008), and a venue's statement is matched against them only to say
which of its positions the ledger has a history for."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine

from open_leprechaun.ports.broker import BrokerAdapter
from open_leprechaun.ports.exchange import ExchangeAdapter, LivePosition, StatesLivePositions
from open_leprechaun.repositories import connections as connections_repository
from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.services import connections
from open_leprechaun.services.connection_sync import failure_sentence
from open_leprechaun.services.connections import CredentialsUnreadableError
from open_leprechaun.settings import Settings

# The kind whose records are futures fills — the one a venue's open positions
# belong beside.
FUTURES_KIND = "futures"


@dataclass(frozen=True)
class StatedPosition:
    stated: LivePosition
    # The open position the ledger derived for the same Account, symbol and
    # side — None where the ledger has no history for what the venue shows.
    ledger_position_id: int | None


@dataclass(frozen=True)
class VenueStatement:
    """One Connection's futures kind: what its venue states, or why nothing
    is stated — a venue without the capability, or a failure in a sentence."""

    connection_id: int
    connection_label: str
    venue: str
    adapter_kind: str
    account_id: int | None
    supported: bool
    error: str | None
    # When the venue answered — the instant its statement stands for. None
    # where it stated nothing: no capability, no answer.
    stated_at: datetime | None
    positions: tuple[StatedPosition, ...]


def ask_venues(
    engine: Engine,
    settings: Settings,
    adapters: Mapping[str, Sequence[ExchangeAdapter | BrokerAdapter]],
) -> tuple[VenueStatement, ...]:
    """Every Connection's futures kind asked in turn; one venue failing
    never hides another (ADR-0004)."""
    with engine.connect() as connection:
        open_positions = futures_repository.open_position_rows(connection)
    statements: list[VenueStatement] = []
    for row in connections_repository.list_connections(engine):
        for adapter in adapters.get(row.venue, ()):
            if adapter.kind != FUTURES_KIND:
                continue
            account_id = connections_repository.paired_account(engine, row.id, adapter.kind)
            error: str | None = None
            stated_at: datetime | None = None
            stated: tuple[LivePosition, ...] = ()
            supported = False
            if isinstance(adapter, StatesLivePositions):
                supported = True
                try:
                    credentials = connections.credentials_of(engine, settings, row.id)
                    if credentials is not None:
                        stated = adapter.live_positions(credentials)
                        stated_at = datetime.now(UTC)
                except CredentialsUnreadableError as sealed:
                    error = str(sealed)
                # Broad on purpose, as in a sync: however one venue failed,
                # the others are still asked.
                except Exception as failed:
                    error = failure_sentence(failed)
            statements.append(
                VenueStatement(
                    connection_id=row.id,
                    connection_label=row.label,
                    venue=row.venue,
                    adapter_kind=adapter.kind,
                    account_id=account_id,
                    supported=supported,
                    error=error,
                    stated_at=stated_at,
                    positions=_matched(stated, account_id, open_positions),
                )
            )
    return tuple(statements)


def _matched(
    stated: Sequence[LivePosition], account_id: int | None, open_positions: Sequence
) -> tuple[StatedPosition, ...]:
    """Each stated position beside the ledger's open one for the same
    Account, symbol and side — each ledger position claimed at most once."""
    unclaimed = [row for row in open_positions if row.account_id == account_id]
    matched: list[StatedPosition] = []
    for position in stated:
        found = next(
            (
                row
                for row in unclaimed
                if row.symbol == position.symbol and row.side == position.side
            ),
            None,
        )
        if found is not None:
            unclaimed.remove(found)
        matched.append(
            StatedPosition(stated=position, ledger_position_id=None if found is None else found.id)
        )
    return tuple(matched)
