# 30 — Aggregates: bots and dust sweeps

**What to build:** Two cases where thousands of tiny records would otherwise drown the ledger: a bot-run strategy, and a venue sweeping many dust balances into one coin. Both are summarised as an aggregate whose constituents remain retrievable, and neither changes a figure.

**Blocked by:** 28

**Status:** ready-for-agent

- [x] A bot's activity is summarised as an aggregate with its constituent fills retrievable
- [x] The capital-income figure from an aggregate equals the sum over its constituents
- [x] A dust sweep is recorded as one aggregate disposal into the received Instrument, with constituents retrievable
- [x] Each constituent disposal still consumes its lots correctly
- [x] No disposal is suppressed from the totals — only from the summary presentation

## Comments

Implemented as one migration (`85b92c2e37fe`: `aggregate` table plus nullable
`transaction.aggregate_id`, SET NULL both ways), `repositories/aggregates.py`,
`services/aggregates.py`, an `/aggregates` router, and `aggregate_id` markers on the three
presentation surfaces (transactions overview, futures overview, §23 disposals). An **Aggregate**
glossary entry was added to CONTEXT.md under Presentation and access.

- **Presentation only, structurally.** No tax engine reads the `aggregate` table. Every summary
  figure is a sum over constituent rows (`SettlementTotals.net` is literally the sum of the
  members' `net_figure`s, the very number each close emits into the Termingeschäfte pot), so the
  ticket's "equals the sum over its constituents" holds by construction and a test pins it
  against `section20.year_report`. §23 disposals keep their own FIFO consumptions and all enter
  the Gesamtgewinn; they merely wear `aggregate_id` for the summary presentation to collapse on.
- **A bot aggregate is a scope, not a member list**: it names the fill `source` it summarises,
  optionally narrowed to one symbol — because derived positions are wiped and rebuilt wholesale
  per source (ADR-0009) and only the scope survives the rebuild. Constituent fills are retrieved
  by the scope; covered positions are marked in the futures overview. Overlapping scopes are
  refused with a sentence (plus a partial-unique-index backstop for exact duplicates), so at most
  one aggregate can claim a position.
- **A dust sweep's members are the constituent trade Transactions themselves**, tagged via
  `transaction.aggregate_id`. Recording validates homogeneity — trades only, exactly one in-leg
  each, all arriving in one Instrument at one Account, no member of another aggregate — and the
  summary re-derives the received side from the ledger as it stands, stating it as nothing if a
  later edit made members disagree rather than answering with one member's view.
- **Deliberately outside the fingerprint** (ADR-0014): membership is presentation like a note, so
  tagging marks no report stale — tested by generating a report, recording the sweep, and
  asserting `stale` stays false. The frozen §23 figures do carry `aggregate_id` from generation
  time onward, so a frozen appendix can collapse the same way.
- **Disband is DELETE**: members are released by the SET NULL constraint; fills, positions and
  Transactions stand exactly as before.

Decisions worth recording:

- `scope_covers` (the one membership rule) lives in `repositories/aggregates.py` so both
  `services/aggregates` and `services/futures` share it without an import cycle — a pure helper
  in a repository module, accepted as the smaller wart.
- The EUR figure per aggregate is not stated by the overview: closed totals stay in the
  settlement currency, and the EUR view is the §20 report's, where each constituent event
  already carries it — stating it twice would invent a second conversion path. The
  sum-over-constituents identity is tested in both currency situations: against the §20 engine
  for an EUR settlement, and in the settlement currency for a foreign one.
- §20 pot entries wear no aggregate marker of their own — the engine must not read aggregates
  (ADR-0013), and each entry's `source` ("futures_position:<id>") maps to the marked position in
  the futures overview. The Anlage-shaped report sections (ticket 51) should collapse bot
  entries through that mapping, as the §23 appendix will through `Disposal.aggregate_id`.
- Two-axis review folded in: `constituents` dispatches once by kind instead of branching twice
  (standards axis), the aggregate repository shares one column list, and the foreign-settlement
  totals test above closes the spec axis's "equality proven only for EUR" gap. Deliberately
  kept: the router's decimal-string serializer copy (the codebase's standing per-router
  convention, as in ticket 28) and the four-kwarg `scope_covers` signature.
- No version bump — releases have not started; this rides as `feat:` like tickets 09–29.
