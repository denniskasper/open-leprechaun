# The first-run checklist derives its state, and a reconciliation records that it ran

## Status

accepted

## Context

The first-run checklist (ticket 58) walks the Admin from an empty database to a first tax report,
and every step's state has to come from real data — never from a flag the Admin dismissed. Six of
the seven steps already leave something to read: an Admin row, an Account, a Connection or
history, pre-flight blockers, a report. Reconciling did not. A reconciliation compared and
answered, and wrote nothing at all (ADR-0008), so "has this Connection been reconciled?" could
only be answered by reconciling it again — a live venue call spent on drawing a checklist.

Two more things were open: what "blockers resolved" means before any report exists, and what a
step is when the walk cannot honestly require it.

## Decision

**The checklist stores nothing.** `GET /first-run-checklist` derives all seven steps on each read
and answers, per step, whether it is done, a sentence saying what that was read from, and the
screen that completes it. A step is open again the moment the thing it asks for is gone.

**A reconciliation records that it ran**, in `connection_reconciliation` — one row per
Connection, replaced by each run: when, how many lines it left open (a gap, or a venue symbol no
Instrument answers to) and how many adapter kinds compared nothing. The step is done when every
Connection's latest run left nothing open. This is a record about the run, not about the ledger:
no quantity is stored, no gap is closed, and the rule that a snapshot never becomes a cost basis
stands unchanged.

**Blockers are resolved once one Tax Year with activity has none.** The walk ends at a first
report, not at every year's; the year still accruing would otherwise hold it open for reasons the
Admin cannot settle yet.

**A step may be optional**, and an optional step never holds completion back. Two-factor is
opt-in (ADR-0005). Reconciling is optional while no Connection's venue states what is held — a ledger fed by
imports alone has no balance to compare against — and required as soon as one does. A
Connection whose venue states nothing is never counted, and a run that compared nothing records
nothing.

**History counts however it arrives.** "Connect or import" is done by a Connection — connecting
is what the step asks — an Import Batch, or a Transaction recorded by hand.

## Consequences

- The recorded run can be older than the ledger: a Transaction added after a clean reconciliation
  leaves the step done until the next run says otherwise. The checklist states what was last
  observed; it does not claim the venue still agrees.
- A reconciliation run with a looser tolerance is recorded like any other, so the step reflects
  the tolerance the Admin last chose.
- Two-factor reads as off on every instance until ticket 08 lands enrolment; the step then reads
  the enrolled secret instead.
- The web had no way to generate a report. The multi-year overview gains a Reports section — the
  screen the last step links to.
