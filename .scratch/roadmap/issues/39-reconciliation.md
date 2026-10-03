# 39 — Reconciliation

**What to build:** The app compares what a venue says is held against what the transactions account for, and surfaces the difference rather than absorbing it. A gap is reported and never filled in by guesswork.

**Blocked by:** 35, 19

**Status:** done

- [x] Reconciliation runs per Connection and reports live balance, tracked balance and the difference per Instrument
- [x] The tolerance is configurable
- [x] A gap is reported and never auto-filled; no cost basis is invented
- [x] Each gap offers the two honest resolutions — import the missing history, or record an Opening Balance with its uncertainty marked
- [x] Synced positions are used for reconciliation only, never as a substitute for transactions
- [x] Works for crypto balances and for cash
- [x] A non-authoritative second source may reconcile against an Account without writing to it

## Comments

Implemented as a capability on the port (`ports/exchange.StatesNormalizedPositions`), one
service (`services/reconciliation.py`), `POST /connections/{id}/reconcile`, the first adapter
to state balances (`OkxSpotAdapter.normalized_positions`), one setting
(`RECONCILIATION_TOLERANCE`) and a Reconcile control with its result table on the Connections
page. No migration — nothing is stored.

- **Per Connection, per kind, per Instrument.** Each kind that states positions is compared
  against its paired Account and reports alone (ADR-0004): an unpaired kind or a failing
  adapter is that kind's error, never a 500 hiding another kind. A line is live, tracked and
  live-less-tracked; `status` is `matched`, `gap` or `unresolved`.
- **Tracked is `Derivation.held`** — the quantity the Holdings view states (ADR-0019), read on
  one snapshot, so the two can never disagree.
- **Tolerance** is absolute, in units of each Instrument: the setting is the standing
  configuration (default one unit of the eighth decimal place), and a run may state its own
  in the request body. A matched line still states the difference it forgave.
- **Never filled.** The service has no write path at all, and a Normalized Position cannot
  reach one: it is not a field of a Harvest, so the sync seam is never handed a snapshot.
  Reconciliation records no per-kind result either — a sync's error is not cleared by it.
- **The two resolutions** ride on each gap as `resolutions`. Importing history is offered in
  both directions; an Opening Balance only where the venue holds more than is accounted for —
  it only ever adds a position, so offering it for a shortfall would be dishonest. The UI
  links the Opening Balance to the ledger form opened on that Account, Instrument and
  quantity; what is reconstructed and the estimated basis stay the Admin's to declare
  (ticket 15's marker is the uncertainty marker).
- **Cash** needs no special case — it is an Instrument (ADR-0011) and resolves within
  `crypto` and `cash`.
- **A second source reconciles without writing.** The authoritative-source rule guards
  writes; reconciliation reads, so it neither checks nor claims the declaration.

Decisions worth recording:

- **A capability, not a port method.** A kind states positions by having
  `normalized_positions`; one without it is passed by and answers nothing. The futures kinds
  do not have it: the ledger keeps their output as Derived Positions and results, not as
  balances. Pionex ships only a futures kind, so it does not reconcile yet.
- **Symbols stay hints (ADR-0010).** A venue symbol resolves to the one Instrument wearing
  it; where several do, the one the Account already tracks answers; otherwise the line is
  `unresolved` with a sentence, and the lines that do resolve are still compared — unlike a
  sync, which must refuse the whole kind because it writes.
- **OKX states funding plus trading balances**, `cashBal` rather than equity. Under a unified
  account that balance carries every settled derivative result, fee and funding payment,
  while the ledger books only a winning close as an acquisition (ticket 29 left the rest
  "reconciliation's to surface"). It surfaces as a shortfall in the settlement asset, and the
  UI's wording for a shortfall names that cause. Whether tracked should instead net those
  results is open — see below.
- **Two-axis review folded in.** Spec axis: dust in an unresolved symbol is now judged by the
  tolerance like any other difference; a balance row the OKX adapter cannot read raises
  AdapterError as the port promises; the adapter's docstring no longer misdescribes what the
  ledger books of a close. Standards axis: the capability and its method name the Normalized
  Position in full (the glossary's _Avoid_ on a bare "Position"); the signed formatter moved
  into `lib/format`; the Opening Balance link's encoding lives beside its decoder; the
  tolerance input shares `DECIMAL_PATTERN`. Accepted as-is: the `Fixed` serializer copied per
  router and the unpaired-kind sentence beside the sync's, both the existing convention.
- No version bump — releases have not started; this rides as `feat:` like earlier tickets.

Open:

- **Futures results in the settlement asset.** A shared Account shows fees, funding and
  losing closes as a standing shortfall that no import can close. Netting them into tracked
  for reconciliation's purposes would remove a known false alarm; it is a modelling decision
  and was not taken here.
- **Securities at a Depot** (story 107) arrive with the broker adapters (tickets 48+), which
  are a different port shape; resolution here covers `crypto` and `cash`.
- The OKX balance payloads in the adapter tests are authored from the documented field
  tables, and the endpoint has not been exercised against the live venue.
- The Reconcile panel was not viewed in a browser — the machine lacks the libraries a
  headless browser needs. Helpers are unit-tested and the page typechecks.
