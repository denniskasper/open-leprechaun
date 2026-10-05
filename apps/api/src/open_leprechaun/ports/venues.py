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

from open_leprechaun.ports.bitpanda import BitpandaSecuritiesAdapter, BitpandaSpotAdapter
from open_leprechaun.ports.broker import BrokerAdapter
from open_leprechaun.ports.coinbase import CoinbaseSpotAdapter
from open_leprechaun.ports.exchange import ExchangeAdapter
from open_leprechaun.ports.okx import EEA_BASE_URL, OkxFuturesAdapter, OkxSpotAdapter
from open_leprechaun.ports.pionex import PionexFuturesAdapter
from open_leprechaun.ports.trading_212 import Trading212Adapter


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
    # Of either account-authenticating port — an exchange's kinds or a
    # broker's; the sync service routes by what a kind pulls, never by name.
    # A venue whose one account holds coins beside securities ships a kind of
    # each. Empty for a venue whose adapters have not shipped — registration
    # works ahead of them; testing and syncing answer nothing.
    adapters: tuple[ExchangeAdapter | BrokerAdapter, ...] = ()


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
            adapters=(OkxSpotAdapter(), OkxFuturesAdapter()),
        ),
        # The venue's EEA entity (my.okx.com): the same API behind its own
        # host, with accounts and keys the global entity does not know.
        Venue(
            venue="okx_eea",
            name="OKX (EEA)",
            required_scope=(
                "Create the API key with the Read permission only — no Trade, no Withdraw."
            ),
            requires_secret=True,
            requires_passphrase=True,
            adapters=(
                OkxSpotAdapter(base_url=EEA_BASE_URL),
                OkxFuturesAdapter(base_url=EEA_BASE_URL),
            ),
        ),
        Venue(
            venue="coinbase",
            name="Coinbase",
            required_scope=(
                "Create the API key with the View (read-only) permission only — no Trade,"
                " no Transfer — and the ECDSA signature algorithm. The API key is the key's"
                " name (organizations/…/apiKeys/…); the secret is its private key."
            ),
            requires_secret=True,
            requires_passphrase=False,
            adapters=(CoinbaseSpotAdapter(),),
        ),
        Venue(
            venue="trading_212",
            name="Trading 212",
            required_scope=(
                "Generate the API key with exactly these scopes ticked: account, portfolio,"
                " history:orders, history:dividends and history:transactions. Leave"
                " orders:execute, orders:read, pies:read, pies:write and metadata unticked."
                " The secret is the API secret shown once beside the key."
            ),
            requires_secret=True,
            requires_passphrase=False,
            adapters=(Trading212Adapter(),),
        ),
        Venue(
            venue="bitpanda",
            name="Bitpanda",
            required_scope=(
                "Generate the API key with exactly these scopes ticked: Balances and"
                " Transaction. Leave Trade (Write) and Earn (Write) unticked; Trade (Read)"
                " and Earn (Read) are not needed. A key lives a year at most — store its"
                " successor before it expires."
            ),
            requires_secret=False,
            requires_passphrase=False,
            adapters=(BitpandaSpotAdapter(), BitpandaSecuritiesAdapter()),
        ),
    )
}
