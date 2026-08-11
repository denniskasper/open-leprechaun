# 43 — Depot, withholding and exemption order

**What to build:** A brokerage account can be registered as a **Depot** with the tax semantics its broker actually has — whether tax is withheld at source, and how much of the saver's allowance has already been consumed there.

**Blocked by:** 10

**Status:** done

- [x] A Depot is an Account under a broker Platform — vocabulary in the UI, not a table or a subtype
- [x] Withholding behaviour lives on the Platform, with a nullable per-Account override for a brand operating through several entities
- [x] A Depot records label, reference and base currency
- [x] Withholding behaviour must be set before a Depot can hold a position
- [x] A nullable exemption-order amount lives on the withholding Platform; absent means none
- [x] A Depot may hold cash balances in one or more currencies

## Comments

Implemented. One revision adds `withholding` and `exemption_order_eur` to `platform` and
`withholding_override` and `base_currency` to `account`; no Depot table exists and nothing
branches on the word — it stays UI copy, as ticket 10 left it.

How each criterion is held:

- **Vocabulary only**: unchanged from ticket 10 — `KIND_VOCABULARY` still says "Depot" for the
  broker kind and nowhere else; the schema gained columns, not a subtype.
- **Behaviour on the Platform, override on the Account**: `platform.withholding` is a nullable
  text pinned by CHECK to `at_source`/`none` and by a second CHECK to `kind = 'broker'`;
  `account.withholding_override` carries the same value CHECK. Effective behaviour is
  `COALESCE(override, platform)` — the Account's word first — expressed in the leg guard's
  SQL, the import evaluation's account read, and `effectiveWithholding` in the web page.
- **Label, reference, base currency**: label and reference existed (`name`,
  `external_reference`); `base_currency` is new, shaped by CHECK to `^[A-Z]{3}$`, and like
  `chain` it is metadata the schema shapes but does not require. The broker's add-Depot form
  offers it; other kinds never see the field.
- **No position against an unknown**: every leg write funnels through
  `repositories/transactions.py`, and each writer (create, replace, bulk reassignment) refuses
  with `Refusal.withholding_unset` — HTTP 409 naming the repair — when any leg would land in a
  broker Account whose effective withholding is NULL. Judged before anything is written, so a
  refusal never half-commits. Imports refuse the same way in `services/imports.evaluate`, so
  the preview names the problem before the commit would.
- **Exemption order**: `exemption_order_eur` is nullable NUMERIC, CHECK non-negative, and CHECK
  `withholding IS NOT DISTINCT FROM 'at_source'` — NOT DISTINCT because a bare equality against
  an unset behaviour evaluates NULL and would let the amount slip past. Absent means none.
  Crosses JSON as a fixed-point decimal string, like every monetary value in the API.
- **Cash in several currencies**: already a consequence of cash-as-Instrument (ADR-0011); a
  test holds a Depot with EUR and USD positions to it.

Decisions worth recording:

- **Withholding is restricted to brokers at the schema.** CONTEXT.md places the behaviour on
  the broker Platform; a bank or exchange carrying one would be an answer to no question. If
  bank interest withholding ever needs modelling, that is a deliberate migration, not a quiet
  reuse.
- **Behaviour and exemption order are one act** (`PUT /platforms/{id}/withholding`), because
  the amount may only stand with the behaviour that gives it meaning; the request model refuses
  the pair `none` + amount with 422 and the schema backs it with the CHECK.
- **The guard is a pre-write check inside the writer's own transaction**, not a trigger — the
  repo has no triggers, and every leg write already funnels through one module. The check runs
  before any INSERT/UPDATE so an early return commits nothing.
- **`imports.account_source` grew kind and effective withholding** rather than a second query,
  so the import evaluation still reads the Account once.
- The seed's broker arrives with `at_source`, a demonstration exemption order and an EUR base
  currency, so a fresh database demonstrates the declared state and its Depot can hold from
  day one.
- Consumption of the Sparerpauschbetrag at source (`allowance_used_at_source_eur` in
  services/section20.py) deliberately stays zero — the exemption order records what is lodged,
  not what income has consumed; wiring consumption is the withholding producer's ticket.
- Post-review fixes (two-axis review): clearing an override that alone answers for a Depot
  already holding legs is refused while the Platform states nothing — the mirror of the leg
  guard, without which the invariant could be broken after the fact; the fifth copy of the
  decimal-string-only JSON validator became one shared `routers/fixed_point.py` used by all
  five routers; the leg guard's logic lives under the honest name `_any_unset_depot` with no
  delegating wrapper; the web client's account URL joined the platforms constant.
