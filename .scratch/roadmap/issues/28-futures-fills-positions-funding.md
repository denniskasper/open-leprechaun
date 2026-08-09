# 28 — Futures fills, positions and funding

**What to build:** Imported futures activity is stored as immutable fills, positions are reconstructed from them, funding is attributed to the position it belongs to, and the whole thing emits Section 20 Events — it computes no tax of its own.

**Blocked by:** 27

**Status:** ready-for-agent

- [x] Fills are stored as received and deduped on source and external identifier
- [x] Positions are derived from the ordered fill sequence per symbol and rebuilt idempotently per source
- [x] Derivation uses position side, reduce-only and per-fill realised result where the venue exposes them, and documented net accounting otherwise
- [x] Manually entered and derived positions share one model and one tax treatment; only origin differs
- [x] Funding is attributed to the position open for that symbol at the payment timestamp
- [x] Funding, trading fees and realised result are stored separately and summed into a net figure
- [x] Unattributable funding is surfaced, never dropped
- [x] A closed position emits a Section 20 Event in the `termingeschaefte` category and computes no tax itself
- [x] A position counts in the year it closed; an open position counts in no year

## Comments

Implemented as one migration (`3e8a5b21c4d7`: `futures_fill`, `futures_position`,
`funding_payment`, `futures_derivation_issue`), `repositories/futures.py`,
`services/futures.py`, a `/futures` router, and the emitter loop in
`services/section20.year_report`.

- **One position model** (`FuturesPosition`): manual and derived rows share the table and the
  dataclass; `origin` says which, a CHECK ties `source` to derived rows alone, and the API
  refuses to revise or remove a derived row (409) — a derivation is the fills' statement,
  corrected only by correcting the fills. Amounts stay in the contract's settlement currency,
  referenced as an Instrument, so the reference-rate universe converts at emission (ADR-0017)
  and a stablecoin-settled contract routes through its peg.
- **The derivation** (`futures.derive`, pure): streams are one account's fills for one symbol,
  split further by `position_side` where the venue states it (hedge mode). Net accounting
  averages the entry, realises reductions against it, and lets a crossing fill close one
  position and open the next with the remainder, fee split pro rata. A venue's per-fill
  realised result is used verbatim where present; reduce-only rules a flip out. A stream the
  flags contradict — a reduce-only fill with nothing open, a hedge-stream reduction beyond
  what is open — derives nothing and lands in `futures_derivation_issue` for manual handling
  (ADR-0009), never a guess.
- **Sync is one transaction**: dedupe-insert fills and funding (`ON CONFLICT` on
  (source, external_id)), wipe and re-derive the source wholesale, re-attribute every funding
  payment. Attribution uses the half-open interval [opened_at, closed_at) and requires exactly
  one candidate; a payment wearing a `position_side` (venue enrichment, added after the
  two-axis review flagged hedge mode as otherwise permanently unattributable) considers only
  that side. Zero or several candidates → `position_id NULL`, surfaced in the overview and as
  a pre-flight blocker — never dropped, never guessed onto a position.
- **Emission**: a closed position emits one event — `net_figure` = realised − fees + funding,
  converted at the close date — into the `termingeschaefte` pot with source
  `futures_position:<id>`; the engine alone nets, caps, carries and rates (ADR-0013). The
  year is the close's Berlin date; an open position emits nothing, however much a partial
  reduction already realised. A settlement only a crypto price can value parks the year as
  awaiting valuation; `Section20Year.awaiting_valuation` now carries source strings
  ("leg:42", "futures_position:7") instead of bare leg ids.
- **Staleness and blockers**: three fingerprint input classes (`futures_fills`,
  `funding_payments`, `manual_futures_positions` — derived rows and attribution are pure
  functions of those, so they are deliberately not fingerprinted); two pre-flight checks
  (unattributable funding up to the report year; derivation issues, unbounded — missing
  history has no year of its own).

Decisions worth recording:

- **The whole net converts at the close date**, not each component at its own instant — the
  gain from a Termingeschäft is determined at Beendigung (§20 Abs. 2 Satz 1 Nr. 3 EStG), so
  the realisation instant prices the figure. Flagged by the spec review as a judgement call;
  recorded here as the deliberate reading.
- **A payment at the exact closing instant is unattributable** (half-open interval): "the
  position open at the payment timestamp" is read as exclusive of the close, and the surfaced
  blocker keeps the case visible instead of silently picking a side.
- **No ingestion endpoint**: `futures.sync` is the seam the adapters (tickets 35+) will call;
  until then only tests and the seed feed it. No web page either — no derivatives screen
  exists yet and no ticket names one; the `/futures` API carries the overview (positions with
  separately stated funding/fees/realised and the net, unattributable payments, issues).
- **Two-axis review folded in**: funding gained the optional `position_side` enrichment (spec
  axis), the net formula deduplicated into `futures.net_figure` shared with the §20 emitter,
  and `derive`'s input typing tightened (standards axis). Deliberately kept: the router's
  decimal-string serializer copy (the codebase's per-router convention — consolidating all
  routers is its own cleanup), and `funding_payment` naming beside CONTEXT.md's "Funding
  Fee" (the definition itself says "payment"; the glossary term may want renaming via
  /domain-modeling later).
- No version bump — releases have not started; this rides as `feat:` like tickets 09–27.
