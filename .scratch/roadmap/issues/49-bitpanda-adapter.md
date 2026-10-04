# 49 — Bitpanda adapter

**What to build:** A second broker on the port, and the first Account that holds crypto and securities at once — proving that regime follows the Instrument rather than the Account.

**Blocked by:** 48

**Status:** done

- [x] The adapter proves the broker port needs no change to accommodate a second venue
- [x] Trades, dividends, cash movements and fees are imported as normalized records
- [x] One Account holding both crypto and security Instruments works end to end
- [x] Crypto positions in that Account are taxed under the private-sale regime and securities under the capital-income regime, with no branching on the Account
- [x] Read-only credentials only
- [x] Tested against recorded fixtures

## Comments

Implemented as one module (`ports/bitpanda.py`) shipping a kind of each account-authenticating
port through the one Connection — `BitpandaSpotAdapter` (exchange port, kind `spot`) and
`BitpandaSecuritiesAdapter` (broker port, kind `securities`) — one registry entry, and one change
to the import framework so both kinds write into the same Depot. The decision is ADR-0026.

How each criterion is held:

- **The broker port needs no change**: `ports/broker.py`, `ports/exchange.py` and
  `services/broker_sync.py` have no diff. Securities, cash, income and fees arrive through the
  broker port exactly as Trading 212's do; the coins arrive through the exchange port, which
  already had the records for them.
- **Trades, dividends, cash movements and fees as normalized records**: the venue serves one
  timeline of operations, each a bundle of transactions. One thing leaving and another arriving
  under one trade is a trade — a coin against cash or another coin on the exchange port, a
  security against cash on the broker port; a single transaction is a cash movement, a coin
  transfer, a dividend, interest or a standalone fee. A trade's fee is stated apart from the cash
  leg it came out of. Everything lands through the import framework.
- **One Account holding both works end to end**: the adapter kinds of one Connection paired with
  one Account are now one ingestion mode — whichever commits first declares itself, and the other
  is not locked out (`alongside`, threaded from `connection_sync` to the row-locked check). Each
  kind keeps its own provenance and deduplication registry. `tests/test_bitpanda_depot.py` drives
  a sync of both kinds into one Depot over the HTTP API.
- **Regime follows the Instrument, no branching on the Account**: nothing in the tax engines
  changed. The same test reads `section23.year_report` and `section20.year_report` after one
  sync: the coin's sale is the only private sale, the share's the only §20 disposal, both from
  the same Account and the same cash.
- **Read-only credentials only**: every request is a GET. The setup screen names the two scopes to
  tick — Balances and Transaction — and the write scopes to leave unticked. `test()` opens every
  endpoint the kind reads and names the scope the key lacks. The asset and currency lists are
  public, so the key is never sent to them.
- **Recorded fixtures**: `tests/fixtures/bitpanda/recorded.json`, replayed through a mock
  transport that honours the key header and the cursor paging.

Decisions worth recording:

- **The fixtures are part recorded, part authored.** The asset and currency rows are the venue's
  own, read from its public endpoints. The operations and the portfolio follow the schemas of the
  published OpenAPI document field for field, but that document prints no examples and names no
  vocabulary for an operation's type, and there was no account to record from. These readings
  rest on that and want confirming against a first real sync: the type names (`deposit`,
  `withdrawal`, `dividend`, `interest`, `fee`, `tax`, `stake`, `unstake`); that a dividend names
  its payer by the transaction's own `asset_id`; that a withheld tax is its own outgoing
  transaction beside the payment; that a trade's fee is inside the cash leg; that a transfer's
  `fee_amount` is charged beside the amount moved; and that an amount's sign may be either. Two
  things came from an integration that reads the live API: only a savings plan's transactions
  carry a type of their own, and a cursor of whole seconds must go back with milliseconds.
- **Read by shape first, by name only where shape cannot say.** A trade needs no type name. A
  single transaction does, and one whose name the adapter does not know is passed over by name —
  never guessed, and never a refusal, since with no documented vocabulary a refusal would bar the
  Depot from syncing over a word. This departs from Trading 212, which refuses an undocumented
  cash type; there the vocabulary is published.
- **The fee-inside-the-cash reading is hedged.** A trade states its rate before and after the fee;
  where the amounts reproduce the rate before it, no fee is taken out of the cash leg.
- **A coin is told from a security by the venue's asset, never by its symbol** — the venue lists
  shares under the symbols of coins. An asset of type `cryptocoin` is the spot kind's; one with an
  ISIN is the securities kind's; a metal or an index is neither and is passed over. The venue
  lists some papers twice under one ISIN; both are the one Instrument.
- **A tax withheld from a dividend lands as the net, the gross beside it** (ADR-0022). The venue
  says what was taken, not by whom or under which law, so no withholding is declared — that stays
  the Admin's. A tax with no income beside it is passed over.
- **Passed over by name**: a reward paid in a coin (the exchange port has no record for income), a
  metal or index trade, a delivery of a security, a movement that takes another back, an asset the
  venue no longer lists. The securities kind names them all, having the only means to; a
  Connection paired for spot alone surfaces none. Each shows as a Reconciliation gap.
- **Staking is not recorded.** A stake or unstake moves nothing in or out of the Depot. The
  Staking Delegation marker stays the Admin's to set.
- **One kind states the Depot's Normalized Positions** — the securities kind, coins included.
  Reconciliation compares a snapshot against everything the paired Account tracks, so two kinds
  each stating a part would report each other's holdings as gaps.
- **The authoritative-source rule changed for every venue, not only this one.** The spec's "exactly
  one authoritative ingestion mode per Account" now reads the kinds of one Connection as one mode.
  `test_a_refused_commit_states_no_coverage` asserted the old reading through two kinds of one
  Connection and was rewritten around a foreign source. A source string names a venue and a kind,
  never the Connection, so a second Connection to the same venue is told apart no better than
  before. Unpairing the kind that declared first leaves its declaration standing; the other kind
  is then refused by name until the Admin re-declares the source.
- **An exchange trade's fee enters no cost basis** — it names no leg it was charged against, as on
  every venue of that port. Seen here because the Depot test states the resulting gain; not
  reopened by this ticket.
- **Two-axis review folded in.** Standards axis: a dividend no longer lands gross with its tax
  passed over; a staking operation no longer hides other legs inside it; a passed-over movement
  names its fee; a public list's refusal no longer blames a key that was not sent. Spec axis:
  ADR-0026 states the Connection caveat instead of claiming more. Accepted as-is: both kinds walk
  the timeline separately on each sync; the request and number-reading helpers repeat the sibling
  adapter's; the Depot test imports the adapter test's mock venue.
- No web change: the setup screen and the Platforms page read the registry generically.
- No version bump — rides as `feat:` like the earlier adapters.
