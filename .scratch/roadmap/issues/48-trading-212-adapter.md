# 48 — Trading 212 adapter

**What to build:** The broker port, proven by a real broker with a read-only API — trades, dividends and cash movements arrive as transactions, and positions arrive for reconciliation only.

**Blocked by:** 34, 43, 44

**Status:** done

- [x] A broker adapter port with a fake, distinct from the exchange adapter port
- [x] Trades, dividends, cash movements and fees are imported as normalized records
- [x] Positions are used for reconciliation only, never as a substitute for transactions
- [x] Foreign-currency trades store the original amount and currency alongside the EUR amount with the rate and rate date used
- [x] A currency-conversion fee attaches to the leg it was charged against and inherits that leg's regime
- [x] Read-only credentials only; the setup screen names the exact scope to grant
- [x] The adapter declares its maximum lookback and reports the period covered
- [x] The UI states that this broker is served by sync
- [x] Tested against recorded fixtures

## Comments

Implemented as a second account-authenticating port (`ports/broker.py`), its first adapter
(`ports/trading_212.py` — `Trading212Adapter`, kind `securities`), a pure translation of a broker
harvest into import rows (`services/broker_sync.py`), one migration (`original_amount`) and three
small UI statements. The recording model is ADR-0025.

How each criterion is held:

- **A broker port with a fake, distinct from the exchange port**: `BrokerAdapter` pulls a
  `BrokerHarvest` of Normalized Security Trades, Dividends, Cash Movements and account fees, each
  security named by ISIN. It shares only what means the same thing at both — credentials, the
  failure type, the cash movement and the position. The fake is `FakeBroker` in
  `tests/test_broker_sync.py`, bound through the same dependency the real registry serves. Both
  ports hang off one Connection and one venue registry (ADR-0004); the sync service routes by what
  a kind pulled, never by a venue's name.
- **Trades, dividends, cash movements and fees as normalized records**: order-history fills become
  trades; the dividend history becomes dividends naming the security that paid; the transaction
  history becomes cash movements, standalone account fees and interest. Everything lands through
  the import framework, so deduplication, the authoritative-source rule and batch reversal apply
  unchanged. An unknown ISIN mints the security flagged for review (ticket 44) instead of refusing.
- **Positions for reconciliation only**: a `BrokerHarvest` has no field for a position, so the
  sync seam can never be handed one; `normalized_positions` is read by Reconciliation alone, which
  now resolves a security by its ISIN (never by the venue's label) and cash by its currency. A
  position in a security the ledger has never seen is an unresolved line, not a minted Instrument.
  This also closes ticket 39's open "securities at a Depot".
- **Original amount, currency, rate and rate date**: the legs are what moved through the Depot —
  the security and the cash the broker debited or credited, in the settlement currency — and the
  trade as it was priced is the Transaction's **Original Amount**, stored beside the legs with the
  broker's rate and the date it is of, answered on `GET /transactions` and shown on the ledger row.
- **Conversion fee attaches to the leg it was charged against**: every fee is its own leg; the
  adapter says whether it was a cost of the security (stamp duty, transaction tax, commission) or
  of the cash (currency conversion), and `charged_against` points there.
- **Read-only credentials, exact scope named**: the setup screen names the five scopes to tick —
  `account`, `portfolio`, `history:orders`, `history:dividends`, `history:transactions` — and the
  ones to leave unticked. `test()` opens every endpoint a sync or reconciliation reads and names
  each scope the key lacks.
- **Lookback declared, period covered reported**: `lookback_days` is `None` (the venue pages the
  whole history), and every harvest states the period it covered, answered with the sync result
  and worded on the Connections page.
- **The UI states the broker is served by sync**: each broker on the Platforms page says whether
  it is served by sync, import or manual entry, and what keeping it current takes.
- **Recorded fixtures**: `tests/fixtures/trading_212/recorded.json`, replayed through a mock
  transport that honours Basic auth and `nextPagePath` paging.

Decisions worth recording:

- **The fixtures are authored, not recorded.** They follow the schemas of the venue's published
  OpenAPI document field for field, but that document prints no example responses and there was no
  account to record from, so every value is invented. Three readings rest on that and want
  confirming against a first real sync: that a fill's `netValue` is the wallet's whole movement,
  fees included; that `taxes` quantities may be signed either way; and the direction of `fxRate`.
  The adapter hedges the last one — it keeps the stated rate in whichever direction reproduces the
  fill's own amounts, and falls back to the rate those amounts imply rather than refuse a trade.
- **Read-only cannot be enforced, only requested.** Unlike Coinbase, the API has no way to state a
  key's own scopes, so `test()` proves the read scopes are present and says plainly that the
  absence of a trading scope is the Admin's to check.
- **The venue now authenticates with a key and a secret** (HTTP Basic); the registry entry
  requires the secret. The legacy single-key header is not used.
- **Passed over by name, not refused.** A split, spin-off or free delivery reaches the order
  history as a fill; a return of capital, demerger or liquidation payment reaches the dividend
  history; a payment taken back arrives negative. None is a transaction the port can express, and
  refusing would bar a Depot from syncing for good after its first split — so each is reported
  with the sync for the Admin to record, and the rest lands. The cash such an event moved is not
  booked, which Reconciliation then shows as a gap. An undocumented *cash transaction type* still
  refuses the pull, as on Coinbase.
- **A conversion fee in a EUR Depot enters no cost basis.** It attaches to the cash leg, as the
  glossary prescribes, and that leg is the numéraire, so no lot and no disposal picks it up. This
  is the documented model applied literally; whether such a fee should instead count as a cost of
  the security it enabled is a tax-treatment question this ticket did not reopen.
- **Dividends state no withholding.** The API gives the net and the gross per share, not what was
  withheld or by whom, so the row declares its payer only and keeps the stated gross in its note;
  the withholding stays the Admin's to declare (ADR-0022). The port and the import framework do
  carry a Quellensteuer with its country and the three German components, exercised through the
  fake, so a broker that states them needs no port change (ticket 49).
- **Pence are normalised.** London prices arrive in `GBX`; the Original Amount is stated in pounds.
- **Everything is recorded as a dividend, never a distribution.** The adapter cannot know a payer
  is a fund; a fund's Teilfreistellung follows the payer named on the row, whatever its type
  (ticket 47).
- **The API serves the primary currency only.** A multi-currency Depot's other balances are not
  stated by it, and neither are pies' internals beyond their uninvested cash.
- `services/exchange_sync.py` became `services/connection_sync.py` (and the dependency
  `get_venue_adapters`): it now lands both ports, and "exchange" names only one kind of Platform.
- **Two-axis review folded in.** Spec axis: the port gained the German withholding components; a
  rate that explains nothing no longer refuses the pull; a negative dividend or interest is passed
  over instead of booked as income; "served by sync" requires a paired kind, not merely a
  Connection. Standards axis: the rename above; the original pricing became one type on the port;
  pence normalised; an undocumented order side refuses instead of booking a sale; the passed-over
  vocabulary is one word from port to screen. Accepted as-is: `covered_days` beside
  `covered_period` (the exchange port reports only the former), the broker port importing its
  shared records from the exchange port's module, and interest travelling as a Normalized Dividend
  of kind `interest`.
- Not viewed in a browser: the three UI additions are covered by unit tests of their wording and
  by typecheck only.
- No version bump — rides as `feat:` like the earlier adapters.
