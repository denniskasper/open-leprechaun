# 19 — Tax Lots as fingerprinted materialisation

**What to build:** Tax Lots are derived from the transaction ledger rather than maintained alongside it, stored only so that holdings and reports need not replay the ledger on every request, and stamped with a fingerprint of the inputs that produced them so a stale lot table is detectable.

**Blocked by:** 13, 14, 15

**Status:** ready-for-agent

- [x] Every acquisition mints a lot; the ledger is the only source of truth
- [x] Lots are derived in full from the beginning of time, never incrementally patched
- [x] Each materialisation records a per-entity fingerprint of its inputs — transactions, corporate actions, instrument classifications, rates used, statutory configuration
- [x] A lot table whose fingerprint no longer matches the ledger is detectable and identified as such
- [x] Rebuilding is idempotent: two runs over unchanged inputs produce identical lots
- [x] An inflow of an unacknowledged Instrument mints no lot

## Comments

Implemented. One revision (`a5813ee813db`) creates `tax_lot` and `input_fingerprint`; the
engine lives in `services/lots.py`, the digest computation in `repositories/fingerprints.py`,
the table swap in `repositories/lots.py`.

How each criterion is held:

- **The ledger is the only source of truth**: a lot's key *is* the in-leg that minted it
  (`leg_id`, PK and FK with cascade) — identity is derived, never assigned, and the cache can
  never block a ledger edit: deleting a Transaction takes its lots with it, and the drifted
  fingerprint marks the survivors for rebuild.
- **Derived in full, never patched**: `rebuild` swaps the whole table inside one REPEATABLE READ
  transaction that also stamps the fingerprint, so the stamp can never describe a ledger the
  derivation did not see. There is no incremental path to drift down.
- **Per-entity fingerprint**: `input_fingerprint(subject, input_class, row_count, digest)` —
  counts and SHA-256 digests per class, computed inside Postgres. Classes today: transactions,
  transaction_legs, instruments (the classification columns), stances, statutory_configuration
  (ticket 09's values), tax_election, plus `rates` and `corporate_actions` declared ahead of
  their tickets (17/18, 52) — those tickets point the class at their new rows, whose first
  real digest then marks the lots stale (an empty table digests like an absent one, so the
  pointing itself drifts nothing). Each class
  digests exactly the columns a derivation reads — a note edit churns nothing (pinned by test),
  a corrected statutory value drifts the table while no transaction has moved (ADR-0014's
  headline consequence, pinned by test). Reports (23) reuse the table under their own subject.
- **Staleness detectable and identified**: `drift(engine)` names each mismatched input class
  with stored and current counts; empty means the stored lots are authoritative. `fresh_lots`
  is the one read, and it rebuilds before returning whenever drift is non-empty — nothing reads
  a persisted lot without the check.
- **Idempotent**: two rebuilds over unchanged inputs produce identical rows, keys included,
  because identity is the minting leg — pinned by test.
- **Unacknowledged mints no lot**: minting is judged per in-leg at derivation time through
  `services/stances.effective_stance` (extracted pure so the engine judges from its own
  snapshot) and `inflow_mints_lot` — only `kept` mints; ignored and dangerous stay visible as
  ledger entries but never enter the cost basis. Even a purchase of an unacknowledged
  Instrument waits in the inbox.

Decisions worth recording:

- **What a lot carries**: quantity, `acquired_at` (the transaction's instant), nullable
  `basis_eur`, and a `basis_source` vocabulary — `cost`, `market_value`, `estimate`,
  `without_consideration` — one column instead of two booleans that could contradict. CHECKs
  hold a windfall to zero basis and an estimate to a present one.
- **A basis the ledger alone cannot state is NULL, never a guess**: a crypto-crypto trade or
  income at market value waits for the rate tickets (17, 18) to extend the derivation; their
  input classes are already declared, so their arrival marks the table stale by itself. A
  purchase mints at cost only when every component (what left, fees charged against the
  acquisition) is the numéraire and the trade has a single acquisition leg — splitting one
  consideration across two positions needs relative market values.
- **The numéraire mints no lot** even under an explicit `kept` stance: every basis is expressed
  in it, so it has none of its own.
- **A fee enters the basis only when charged against the acquiring leg** (ADR-0011): charged
  against the disposal it is that disposal's cost, ticket 21's business.
- **Digest determinism**: rows serialise with unit/record separators, instants render at UTC via
  `to_char` (the session timezone must not leak into a digest), lines aggregate under `COLLATE
  "C"`. The empty digest is SHA-256 of nothing, shared by empty tables and not-yet-built
  classes — so a class's table arriving empty does not spuriously drift.
- `services/lots.py` is the first reader of `services/tax_treatment.py`; the import-scan test
  now pins the reader list to exactly it.
- Coordinated in-flight with ticket 09 (separate session, same checkout): the migration chains
  after `fc41e1dbaccd`, and the statutory store's tables joined the fingerprint the day both
  landed. `tax_election` is its own input class — a changed election is a different staleness
  message than a corrected statute.
- No version bump — releases have not started; like tickets 10–15 this rides as `feat:` until
  one is cut.
- Post-review fixes (two-axis review): `fresh_lots` now runs check, rebuild and read on **one
  REPEATABLE READ snapshot** — no ledger edit can slip between the check and the answer, the
  fingerprint is computed once instead of twice on the rebuild path, and
  `repositories/lots.list_lots` takes that Connection so no import can serve a lot the check
  did not cover; the windfall CHECK closed its NULL hole (`basis_eur IS NOT NULL AND basis_eur
  = 0` — a SQL CHECK passes on NULL); `fresh_lots` answers `Lot` dataclasses rather than raw
  rows, the shape tickets 20/21 will consume; the declared-empty-class prose overstated the
  mechanism and now says who does the pointing. Deliberately not taken: sharing one column
  list between the digest queries and the ledger reads (the two render columns differently —
  UTC `to_char` vs raw — and the note-edit/quantity-edit tests pin the invariant that
  matters), and a `LedgerSnapshot` bundle for `derive`'s arguments (the explicit signature is
  the pure seam's documentation).
