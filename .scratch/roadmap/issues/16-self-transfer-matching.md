# 16 — Self-transfer matching

**What to build:** Moving assets between the Admin's own Accounts stops looking like a sale and a fresh purchase. The app proposes candidate matches; the Admin confirms or rejects; a confirmed link carries basis and acquisition date across.

**Blocked by:** 13

**Status:** done

- [x] Candidates are proposed by Instrument, quantity within a fee tolerance, and time window
- [x] The Admin confirms or rejects each proposal; nothing links itself
- [x] A confirmed link carries the original cost basis and the original acquisition date across
- [x] The same mechanic works for a transfer between two Depots, preserving lot identity
- [x] An unmatched transfer is visible as unmatched, never quietly treated as a disposal

## Comments

Implemented. One revision (`43bbb4857d4f`) creates `transfer_match` and re-keys `tax_lot` on
`(leg_id, ordinal)`; the candidate rule and read model live in
`services/transfer_matches.py`, the decisions in `repositories/transfer_matches.py`, the
carry itself in `services/lots.py`, and the screen at `/transfers` (nav section "Ledger").

How each criterion is held:

- **Candidates proposed**: a candidate is a derived query, never a row — the stance idiom.
  `is_candidate` (pure, pinned at its boundaries by test) pairs the out-leg of a
  `transfer_out` with the in-leg of a `transfer_in`: same Instrument, two different Accounts,
  no more arriving than left, the shortfall within `QUANTITY_TOLERANCE` (1% of what left —
  the fee), the instants within `TIME_WINDOW` (72 h, symmetric, because venue clocks
  disagree). The numéraire is exempt throughout: moving EUR is no disposal, so its transfers
  are neither unmatched nor proposable.
- **Confirm or reject, nothing links itself**: `GET /api/transfer-matches` stores nothing
  (pinned by test); only `POST` writes, and only the Admin presses it. A decision row is
  `confirmed` or `rejected`; partial unique indexes hold each leg to one confirmed match per
  side while rejections accumulate freely, and one decision per pair keeps the verdicts from
  contradicting each other. A rejected pair is never proposed again; `DELETE` undoes either
  verdict (unlink, or make proposable again). Confirming is judged looser than proposing —
  tolerance and window are proposal heuristics, so an out-of-window pair the Admin knows
  better about is accepted, while what cannot be a self-transfer at all (wrong shapes, mixed
  Instruments, one Account, more arriving than left, the numéraire) is refused 422 with a
  sentence.
- **Basis and date carried**: the lot engine now replays the ledger chronologically with a
  FIFO queue of slices per (Account, Instrument): minting in-legs push, out and fee legs
  consume, and a confirmed match routes what its out-leg consumed to its in-leg's Account.
  The destination lot wears the source slice's original `acquired_at`, `basis_eur` and
  `basis_source` — the Haltefrist never restarts, and an Opening Balance's `estimate` stays
  an estimate so ticket 21 still flags disposals resting on it. Confirmed links are a new
  fingerprint input class (`transfer_matches`, confirmed rows only), so a confirmation
  reaches the very next read by itself; rejections change proposals, never lots.
- **Depots, preserving lot identity**: the mechanic never branches on family — a securities
  test pins a Depotübertrag carrying the lot intact. A parcel spanning several acquisitions
  arrives as several lots, never merged into an invented average, which is why `tax_lot` is
  now keyed `(leg_id, ordinal)` — identity still derived, never assigned.
- **Unmatched stays visible**: the screen lists every undecided transfer leg under an
  `unmatched` marker, and `transfer_out` remains `awaiting_match` in
  `services/tax_treatment.py` (its test unchanged). An unmatched or rejected transfer mints
  nothing and disposes nothing (pinned by test).

Decisions worth recording:

- **What went missing en route burns from the head**: when less arrives than left — a
  network fee — the shortfall comes off the oldest slices first (FIFO: the fee is the first
  thing the parcel gave up), so the destination never claims an older acquisition than it
  can prove. A pro-rated basis is stated in cents with the exact remainder on the other
  part; no cent invented or lost.
- **What the source cannot vouch for carries nothing**: a transfer out of a holding no lot
  supports (an unclassified inflow, an ignored position) arrives without a lot rather than
  inventing an acquisition at the destination.
- **The confirmation is the classification**: a matched arrival no longer waits in the inbox
  and a keep never retypes it to airdrop/windfall (both stance queries exclude confirmed
  in-legs) — but a standing ignored or dangerous decision at the destination still blocks
  the mint, as it blocks every mint.
- **Decisions follow their legs by cascade**: revising a Transaction swaps its legs, so the
  match honestly returns to unmatched rather than pointing at quantities the Admin never
  confirmed.
- **Deposit stamped before withdrawal**: venue clocks disagree, so the engine consumes the
  source queue eagerly when the in-leg processes first — deterministic either way.
- The seed adds the withdrawal side (`transfer_out`, Kraken, keyed on type and instant) so
  the development matching screen has a proposal waiting; nothing is pre-confirmed.
- The e2e spec arranges its own transfer pair over the API on the seeded BTC and walks
  propose → confirm → unlink through the browser, skipping on an unseeded database.
- No version bump — releases have not started; like tickets 10–15 and 19 this rides as
  `feat:` until one is cut.
- Post-review fixes (two-axis review): the two head-trimming loops in the engine collapsed
  into one `_behead` helper that `_consume` and `_arrived` both call; the candidate card now
  uses the shared `MutationAlert` instead of hand-rolling its error paragraph, and
  `useDecide` was renamed `useInvalidateOnDecision` to say what it does; the two untested
  paths the spec axis named are now pinned — a deposit stamped before its withdrawal (the
  eager-consumption path) and a confirmation the proposal rules would not have made (fee far
  beyond tolerance) both carry correctly; the head-burn policy and the deliberate silence
  over the burnt portion's basis are recorded as **ADR-0016** rather than only here.
  Deliberately not taken: bundling `derive`'s working state into an object (the explicit
  signatures document the seam, the same call ticket 19 made against a `LedgerSnapshot`);
  collapsing the four spellings of the TransferLeg shape (each layer's own shape is the
  repo's layering idiom); moving `trimDecimal` into `lib/format.ts` (it shapes strings for
  comparison, not display — it moves the day a second screen needs it). The undo endpoint
  (`DELETE`) stays: scope surplus against the ticket's letter, but a rejection that could
  never be reconsidered and a link that could never be unlinked would make every decision
  irreversible, against how every other decision in this app behaves.
