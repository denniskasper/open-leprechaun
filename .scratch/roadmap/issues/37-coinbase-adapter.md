# 37 — Coinbase adapter

**What to build:** A third exchange on the port, covering spot trades, transfers and cash movements.

**Blocked by:** 35

**Status:** done

- [x] Spot trades, transfers and cash movements are imported as normalized records
- [x] Read-only credentials only; the required scope is named in the UI
- [x] The adapter declares its maximum lookback
- [x] Tested against recorded fixtures

## Comments

Implemented as one adapter (`ports/coinbase.py` — `CoinbaseSpotAdapter`, kind `spot`) plus the
registry entry gaining its `adapters` tuple and a fuller scope sentence (`ports/venues.py`). No
migration, no port change, no service, router or screen change.

- **Two venue APIs behind one kind**: spot trades come from the brokerage API's fills
  (`/api/v3/brokerage/orders/historical/fills`, `product_types=SPOT`); crypto transfers and
  fiat cash movements from the account API's per-wallet transactions (`/v2/accounts`, then
  `/v2/accounts/:id/transactions`). The account API repeats each fill as one row per wallet
  (`advanced_trade_fill`) and shows moves between the venue account's own wallets (`transfer`)
  — both are passed by, so nothing lands twice.
- **Auth**: a JWT per request, ES256, signed with `cryptography` directly (no new dependency) —
  key name as `kid`/`sub`, issuer `cdp`, two minutes of life, a nonce, and a `uri` claim of
  method, host and path without the query. The credential's key is the key name, its secret
  the EC private key. The PEM is read however it was pasted — real line breaks, the key file's
  escaped ones, or none at all, since the setup screen's secret field is a single line that
  swallows them. An Ed25519 key refuses with the algorithm to choose; no sentence carries
  secret material.
- **Read-only enforced, not just requested** (ADR-0003): `/key_permissions` states the key's
  own permissions, and `test()` fails unless Trade and Transfer are each an explicit `false`.
  The setup screen's scope text now names the exact vocabulary — View only, no Trade, no
  Transfer, ECDSA — and says which half of the key file goes in which field.
- **Lookback declared as unbounded**: `lookback_days` is `None`, which the screen already
  words as "The venue serves its full history." Every sync therefore walks the whole history
  (the import framework deduplicates), under a page budget of a hundred thousand rows per
  walk that raises on exhaustion rather than stopping short.
- **Quirks absorbed**: two error dialects (`{"error","message"}` or a bare-text 401, and
  `{"errors":[…]}`); two pagination dialects (an opaque `cursor`, and a `next_uri` that is
  followed only while it stays a path on the account API, so a token never leaves the venue's
  host); a send's `amount` stated gross of its network fee, split into quantity and fee; the
  amount's sign, not the type, deciding a send/receive's direction; offsets normalised to UTC.
- **Fixtures are the documentation's own example payloads** — the fill, the key permissions,
  the wallet, the on-chain and off-chain sends — with the repairs the test file states
  (a completed status; the docs' "ETH" typo beside BTC amounts). The docs print no receive and
  no fiat movement, so those three are authored from the transaction field table and marked.
  No live recording exists: there was no Coinbase account to record from.

Decisions worth recording:

- **Undocumented movement types refuse the pull by name.** A simple `buy` or `sell`, a
  `trade` (conversion), a reward or staking move: the documentation states neither their
  counter-amount, their fee, nor whether the cash side came from a fiat wallet or straight from
  a bank. Skipping them would land a history with holes; guessing would book wrong lots. So a
  completed row of any such type refuses the kind, naming every type found, and points at the
  venue's export instead. **This is the adapter's main limit**: a venue account that ever used
  the simple buy/sell flow cannot sync through it until those shapes are added from a real
  recording. Advanced Trade fills, sends, receives and fiat movements are what it serves today.
- **A fill that amends another refuses** (`trade_type` other than `FILL`), and so does a fiat
  movement whose sign contradicts its type — a reversal is not the movement it undoes.
- **A quote-sized fill** (`size_in_quote`) states `size` in the quote currency, the base
  following from the price, the commission a separate fee leg. The docs say only that the
  order "was placed with quote currency"; whether that size is gross of commission is not
  stated, so this is an interpretation to confirm against a first real sync.
- **No positions capability yet**: the kind does not state balances for reconciliation
  (ticket 39) — not asked for here; the wallet list would serve it.
- **Two-axis review folded in.** Standards axis: malformed rows now surface as `AdapterError`
  (the port's promise) rather than bare `KeyError`/arithmetic faults; an offset-less timestamp
  reads as UTC, never server-local; a zero-amount row is passed by; the page budget counts
  exactly; a local no longer shadows "kind"; venue wallets are called wallets, not accounts.
  Spec axis: the read-only check no longer passes on absent flags; cash direction is checked
  against the sign; the page budget grew to suit an unbounded history. Accepted as-is: the
  transport scaffolding shared in shape with okx and pionex (per-port quirk confinement is
  the documented idiom), the scope sentence also saying which credential field is which (the
  screen has no other place for it without a structure change), `transaction_amount` not
  cross-checked, and an empty sync of an unbounded venue saying "Nothing to pull for this
  kind." without a period (ticket 40's wording).
- No version bump — rides as `feat:` like the earlier adapters.
