# 35 — Exchange adapter port; first adapter

**What to build:** The port that confines a venue's quirks, proven by one real exchange working end to end — credentials in, normalized records out, transactions in the ledger. Core code never learns a venue's name.

**Blocked by:** 34, 31

**Status:** ready-for-agent

- [x] An adapter translates a venue's API into canonical normalized records — trade, transfer, fill, funding, cash movement, position
- [x] Adapters never touch the database, never convert to EUR and never compute tax
- [x] Pagination, rate limits, capped lookback, symbol discovery and request signing are absorbed inside the adapter
- [x] Adding a venue means one adapter plus a registry entry — no changes to services, routers or the UI
- [x] Testing and syncing act on the Connection and report results per adapter kind, so one kind failing does not hide another succeeding
- [x] One real exchange adapter ships and imports history end to end
- [x] Adapters are tested against recorded fixtures of real venue responses, with no live calls in CI

## Comments

Implemented as the port (`ports/exchange.py`), the sync seam (`services/exchange_sync.py`),
one migration (`a7c31f92e4b8`: `connection_account` pairing), test/sync/pairing endpoints on
the `/connections` router, the first adapter (`ports/pionex.py` — the spec's "portable from
existing work" venue), its registry entry in `ports/venues.py`, and per-kind pairing, Test and
Sync on the Connections settings page.

- **The port** (`ports/exchange.py`): an adapter is `kind` + `test(credentials)` +
  `pull(credentials) -> Harvest`; the Harvest carries Normalized Trade, Transfer, Cash
  Movement, Fill and Funding, each naming assets by the venue's **symbols alone** — an adapter
  cannot know an Instrument id or Account, which is what makes "never touches the database"
  structural. Credentials arrive as a Protocol the Connection service's dataclass satisfies.
  The registry (`ports/venues.py`) gained `adapters` per venue; a DI provider
  (`adapters.py`, mirroring `prices.py`) hands the mapping to the router so tests bind fakes
  of the port through the same seam production uses.
- **The sync seam** (`services/exchange_sync.py`) is the one place adapter output meets the
  ledger. Venue symbols resolve against existing Instruments — exactly one may wear the
  symbol (crypto or cash; cash alone for a cash movement's currency); none or several refuses
  the kind with a sentence, because a symbol is a resolution hint, never an identity
  (ADR-0010), and minting identity from a bare symbol is exactly what the Instrument model
  forbids. Fills/funding route to `futures.sync` (ticket 28), ledger-bound rows through
  `imports.commit` (ticket 31) — dedup, authoritative-source and batch reversibility all
  inherited, nothing reimplemented. Source string is the per-kind provenance `<venue>:<kind>`.
- **Per-kind everything** (ADR-0004): each kind has its own Account pairing
  (`connection_account`, upsert per (connection, kind), Account must sit under the
  Connection's own Platform), its own recorded result, its own error. A kind's adapter
  raising anything — even an untranslated bug — becomes that kind's error, never a 500 hiding
  the other kind's success. `CredentialsUnreadableError` alone is global (409: re-entry).
- **Pionex** ships the futures kind: HMAC signing (scheme verified live in the previous
  implementation and pinned by tests), symbol discovery via open + paged closed orders,
  90-day lookback walked in 60-day windows paged backwards by timestamp cursor, page budgets
  that raise on truncation rather than silently stopping short. Fills carry no enrichment
  (net accounting derives); USDT-quoted perps are linear (`inverse=False`), anything else
  stays unstated and derivation refuses the stream. Verified against the live venue in dev:
  a request signs, transport works, and a bad key comes back as the kind's recorded sentence.
- **Tested at the two spec seams**: the API over real Postgres with port fakes
  (`test_exchange_sync.py` — pairing, per-kind test/sync, futures landing end to end with the
  derived position's net figure, ledger landing with batch + provenance + idempotent re-sync +
  authoritative-source claim, symbol refusals), and the adapter against recorded fixtures
  (`test_pionex_adapter.py` — no live calls; the mock venue honours span and limit params).

Decisions worth recording:

- **Normalized Position is vocabulary now, consumer later.** The port defines the record —
  a snapshot of what the venue says is held, explicitly never a derivation input (ADR-0008
  rejected venues supplying finished positions) — but no adapter emits one until
  reconciliation (ticket 39) asks. Security Trade and Dividend stay with the broker adapter
  (tickets 43+), a different port shape.
- **Adapters declare `lookback_days`** (ADR-0008's capability): Pionex states 90; ticket 40
  turns the declaration into the per-Connection wording and the coverage warning.
- **No auto-creation of Instruments from a sync.** The import framework auto-creates from a
  full identity spec; an adapter has only a symbol, so the sync refuses and names the symbol —
  the Admin creates the Instrument once, and the next sync (idempotent) picks everything up.
- **Pionex bots are not a port record.** v1 ingested per-bot totals; v2's ticket 30 already
  models a bot as an aggregate *scope over fills*, so bot activity arrives through the same
  fills sync and the Admin records the aggregate scope over it.
- **`repositories/futures.NormalizedFill` keeps its name** beside the port's new
  `NormalizedFill`: the domain term belongs to what a port emits, the repository's is its
  resolved twin (account and settlement Instrument attached). Renaming the ticket-28 type was
  out of scope; callers qualify by module.
- The venues endpoint gained `adapter_kinds` so the UI can offer pairing before anything has
  synced; venues without adapters honestly answer an empty list and the UI says the adapter
  has not shipped yet.
- **Two-axis review folded in.** Spec axis: `_paged` now lands its cursor *on* the oldest
  instant of a full page and deduplicates the boundary rows instead of stepping past them —
  a full page could cut through one millisecond and the old cursor silently dropped whatever
  shared it (rows the API hides beyond a full page at a single instant remain unreachable by
  any client; the walk drains what is visible and terminates); and a Connection deleted
  between lookup and decrypt now answers 404 instead of misattributing the race to the
  adapter. Standards axis: an unexpected (non-AdapterError) exception records only its type —
  its message promises nothing about secret material (ADR-0003) — sync-result counts format
  through `lib/format`, the port's side/direction fields are `Literal` types, and the two
  result handlers on the page share one helper. Accepted as-is: the
  (engine, settings, adapters, connection_id) parameter clump, and the unpair endpoint
  shipping without a UI consumer (the API's recovery for a mispairing).
- No version bump — releases have not started; this rides as `feat:` like earlier tickets.
