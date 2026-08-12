# 36 — OKX adapter

**What to build:** A second exchange on the port, syncing spot, futures and cash movements forward from an account with no prior history.

**Blocked by:** 35

**Status:** done

- [x] Spot trades, transfers, futures fills, funding and cash movements are imported as normalized records
- [x] The adapter proves the port needs no change to accommodate a second venue
- [x] Sync from an account with no history completes cleanly and reports the period covered
- [x] Read-only credentials only; the setup screen names the exact scope to grant
- [x] Tested against recorded fixtures

## Comments

Implemented as two adapters in one module (`ports/okx.py` — `OkxSpotAdapter` and
`OkxFuturesAdapter` over a shared signing/transport base), the registry entry gaining its
`adapters` tuple (`ports/venues.py`), and one small sync-seam addition: `KindSync.covered_days`,
surfaced through the router, the zod schema and `describeSyncResult`. No migration, no port
change, no service or UI structure change — OKX is the first venue with more than one kind, and
the per-kind pairing, test and sync paths shipped by ticket 35 carried it unmodified.

- **The port did not move** (the ticket's proof): `ports/exchange.py` is untouched. The spot
  kind emits Normalized Trade, Transfer and Cash Movement — the first real producer of all
  three, previously exercised only by fakes — and the futures kind emits Fill and Funding.
- **Auth**: Base64 HMAC-SHA256 over `timestamp + METHOD + path?query + body`, ISO-millisecond
  timestamp, four `OK-ACCESS-*` headers. OKX is the first venue whose key carries a passphrase,
  so the registration-time `requires_passphrase` path and the credential's third field are
  exercised end to end for the first time. A missing secret or passphrase refuses before any
  request leaves.
- **Read-only enforced, not just requested** (ADR-0003): `/account/config` states the key's own
  permission set, and `test()` fails a key granting `trade` or `withdraw` with the scope to
  mint instead. The setup screen's scope text ("Read permission only — no Trade, no Withdraw")
  already named OKX's exact permission vocabulary.
- **Quirks absorbed**: logical errors as HTTP-200-or-401 plus `{"code" != "0"}`; three distinct
  pagination dialects — fills and bills backwards by `billId` cursor (unique, so no boundary
  instant can be cut), asset transfer history by an exclusive timestamp cursor, fiat order
  history by inclusive time filters — the two instant-paged dialects sharing Pionex's
  land-on-the-boundary-and-deduplicate walk; page budgets that raise on exhaustion rather than
  silently stopping short; contracts sized by the public instrument descriptions (linear
  `fillSz × ctVal × ctMult` in the base currency, inverse in USD), with an undescribed contract
  refusing by name rather than guessing a face value.
- **OKX states what Pionex could not**: `posSide` (hedge mode) becomes the port's
  `position_side`, `fillPnl` the per-fill `realized`, and `ctType` a truthful `inverse` — which
  is exactly what lets an inverse stream derive at all (ticket 28's rule that a coin-settled
  stream needs venue-stated results). A description stating neither variant leaves `inverse`
  unstated and derivation refuses, never defaults to linear.
- **Signs**: the venue writes charges negative and rebates positive. Fills negate into the
  port's positive-is-a-cost convention, so a futures maker rebate arrives deliberately as a
  negative cost the net accounting sums into the position. A *spot* rebate refuses instead —
  the ledger's fee leg has no shape for income. Funding is read from the bill's `pnl` (the
  documentation's own pointer), already signed the port's way.
- **Period covered** (the ticket's empty-account criterion, the minimal slice of ticket 40):
  a successful sync answers `covered_days` from the adapter's declared `lookback_days` (90 —
  OKX serves three months of fills and bills), and the UI says "Nothing to pull — the last
  90 days are covered." for an empty account instead of a bare nothing. A kind that failed, or
  whose commit was refused, states no coverage — an error and a coverage claim would
  contradict. Ticket 40 keeps the per-Connection wording and the dashboard warning; an
  unbounded-lookback venue will need richer wording when one ships.
- **Fixtures are the documentation's own example payloads** (timestamps rebased into the
  lookback window), with two exceptions the test file marks: the docs print no SWAP
  fills-history row and no funding-fee bill, so those two are authored from the documented
  field tables — verified against the docs' field semantics, not against a live recording,
  since no OKX account history existed to record. The mock venue honours each endpoint's real
  pagination contract, so the walks are genuinely exercised.

Decisions worth recording:

- **Two kinds, not three**: transfers and fiat movements ride with the spot kind — they are
  ledger-bound records landing in the same Account a spot trade does; a third pairing would
  buy nothing.
- **A fee-bearing fiat order refuses**: whether the venue states the order amount beside or
  net of its fee is undocumented, and the port's Cash Movement carries one amount — refusal
  with the order named beats a guessed balance.
- **Dated FUTURES ride with SWAP** under the one futures kind; OPTION stays out — not a
  Termingeschäft shape this ledger models yet.
- **Pending transfers stay out** (deposit/withdrawal state ≠ success, fiat ≠ completed): a
  movement still in flight arrives on a later sync once the venue calls it settled, keeping
  the pull idempotent without modelling venue state machines.
- **Two-axis review folded in.** Standards axis: a description missing `ctType` no longer
  defaults to linear (`inverse` stays unstated, per the domain rule); the truncation sentence,
  derivative-type tuple and fiat direction each live in one place; the config unpack reads
  plainly. Spec axis: a refused commit no longer claims coverage beside its error (seam test
  added); a futures rebate's negative-cost path is now a stated, tested behaviour rather than
  a silent one. Accepted as-is: the transport/error scaffolding okx shares in shape with
  pionex (per-port quirk confinement is the documented idiom; a third venue may earn the
  extraction), the four-argument cursor-dialect signature of `_paged_by_instant` (two call
  sites, named at both), and the theoretical loss of >100 same-millisecond rows on the
  instant-paged endpoints (the venue hides them from any client; same acceptance as ticket
  35's boundary note).
- No version bump — releases have not started; this rides as `feat:` like earlier tickets.
