# 29 — Coin-margined settlement

**What to build:** An inverse contract settles in the coin rather than a quote currency, so closing one both realises capital income and puts an asset into the ledger. Both consequences are recorded, and neither needs a special rule beyond this ticket.

**Blocked by:** 28, 19

**Status:** done

- [x] A coin-margined close emits a Section 20 Event for the result, converted at the rate of the close
- [x] The same close mints a Tax Lot for the settlement asset at its EUR value at close time
- [x] The minted lot's holding period starts at the close
- [x] Connectors and adapters that cannot support the variant refuse it explicitly rather than converting it wrongly
- [x] Tested end to end: a close produces exactly one capital-income event and exactly one lot

## Comments

Implemented. One migration (`c4b9d21aa7e6`): `futures_fill.inverse` (nullable — NULL means the
port did not say), and `tax_lot.leg_id` made nullable with the primary key replaced by two
partial unique indexes, because a settlement lot is minted by no in-leg and keys on
(account, instrument, acquired_at, ordinal). Deliberately no foreign key to `futures_position`:
derived rows churn ids on every sync, and a cascade would empty the materialisation without
moving its fingerprint.

- **Section 20 Event**: ticket 28's emitter already covered it — the net figure converts at the
  close instant by `fx.value_eur` over the settlement Instrument; a settlement only a crypto
  price can value waits as `awaiting_valuation` until historical resolution (ticket 41).
- **The lot**: `lots.derive` now takes the closed positions of the futures store (ADR-0009's
  second source of truth) and walks them beside the transactions in close order
  (`services/lots._settlement`): a positive net figure in a non-numéraire settlement Instrument
  mints one lot — `leg_id` None, `acquired_at` the close (Haltefrist from there),
  `basis_source` market_value with the basis stated at report time by the same rule and instant
  that valued the event, so income and basis cannot disagree. The rule is deliberately
  variant-agnostic: a linear contract's stablecoin or foreign-cash profit is the same
  acquisition. Holdings (`_held`) adds the same positive nets, so quantity and lot queue agree;
  §23 consumes the lot FIFO like any other. The fingerprint registry already listed the futures
  tables as `tax_lots` inputs, so a new fill marks the lot table stale by itself.
- **Refusal**: derivation refuses a stream whose variant is unstated (NULL), whose fills
  disagree on it, or that is inverse without venue-stated per-fill realised results — net
  accounting would state a coin-settled result in the quote currency's unit. Each lands in
  `futures_derivation_issue`, surfaced like every other unreconcilable stream. There are no
  venue adapters yet (tickets 35+); the port contract (`NormalizedFill.inverse`) binds them to
  state the variant or refuse the account.
- **Out of scope, recorded here**: a losing close mints nothing and reduces no holding — the
  coin the loss took from the margin is a disposal question this ticket does not pose, and the
  venue-side drift it leaves is reconciliation's to surface (ticket 39). `CONTEXT.md` gained an
  **Inverse Contract** entry.

Tested end to end in `tests/test_coin_margined.py`: one close produces exactly one
Termingeschäfte event and exactly one lot, and a later disposal consumes that lot at the
close-time basis with the holding period running from the close.
