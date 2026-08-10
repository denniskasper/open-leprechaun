"""The venue registry: every venue a Connection may speak to, with what its
credential must look like and the scope the Admin should grant.

This is the one place venue names live on the way in (ADR-0004, ticket 35's
"one adapter plus a registry entry") — core code reads entries generically and
never branches on a name. Every scope is read-only by design: the application
never holds a credential that could place an order or move funds, so each
entry's scope text says exactly which read permission to grant and nothing
more.
"""

from dataclasses import dataclass

from open_leprechaun.ports.exchange import ExchangeAdapter
from open_leprechaun.ports.pionex import PionexFuturesAdapter


@dataclass(frozen=True)
class Venue:
    """What the UI and the Connection service need to know before any adapter
    exists — how this venue's credential is shaped and what to ask it for —
    plus the adapter instances the venue ships, one per kind it serves."""

    venue: str
    name: str
    # UI copy: the read-only permission set the Admin grants when minting the
    # key at the venue.
    required_scope: str
    # Whether the venue signs requests with a separate secret, or the API key
    # alone is the whole credential.
    requires_secret: bool
    # A third factor some venues attach to the key itself.
    requires_passphrase: bool
    # Empty until the venue's adapters ship (tickets 35-37, 48-49) —
    # registration works ahead of them; testing and syncing answer nothing.
    adapters: tuple[ExchangeAdapter, ...] = ()


# Keyed by the registry string a Connection stores. Adding a venue is adding
# an entry here (plus, one day, its adapter) — never a migration and never a
# service change.
VENUES: dict[str, Venue] = {
    entry.venue: entry
    for entry in (
        Venue(
            venue="pionex",
            name="Pionex",
            required_scope=(
                "Create the API key with the Read Data permission only — no Trade, no Withdraw."
            ),
            requires_secret=True,
            requires_passphrase=False,
            adapters=(PionexFuturesAdapter(),),
        ),
        Venue(
            venue="okx",
            name="OKX",
            required_scope=(
                "Create the API key with the Read permission only — no Trade, no Withdraw."
            ),
            requires_secret=True,
            requires_passphrase=True,
        ),
        Venue(
            venue="coinbase",
            name="Coinbase",
            required_scope="Create the API key with the View (read-only) permission only.",
            requires_secret=True,
            requires_passphrase=False,
        ),
        Venue(
            venue="trading_212",
            name="Trading 212",
            required_scope=(
                "Generate the API key with read scopes only — orders and trading stay unticked."
            ),
            requires_secret=False,
            requires_passphrase=False,
        ),
        Venue(
            venue="bitpanda",
            name="Bitpanda",
            required_scope="Issue the API key with read scopes only — no trading scope.",
            requires_secret=False,
            requires_passphrase=False,
        ),
    )
}
