# 58 — Guided first-run checklist

**What to build:** A checklist that walks the Admin from an empty database to a first tax report, where every item's state is derived from real data rather than from a flag someone dismissed.

**Blocked by:** 39, 25

**Status:** done

- [x] The checklist covers: set a password, enable two-factor, add Platforms and Accounts, connect or import, reconcile, resolve blockers, generate a report
- [x] Each item's done state is derived from real data, never from a dismissible flag
- [x] Each undone item links to the screen that completes it
- [x] Every empty state across the app explains what to do next
- [x] Every error names the thing that failed and the action that fixes it

## Comments

Landed as `GET /api/first-run-checklist` and the `First run` screen (`/first-run`), which a fresh
instance opens on after setting its password. Decisions are in ADR-0030; the term is in
`CONTEXT.md`.

- **Derived, never stored.** Each step is read from the database on every request: an Admin row;
  an Account; a Connection, Import Batch or Transaction; every Connection's last reconciliation
  leaving nothing open; a Tax Year with activity and no pre-flight blockers; a report. Removing
  the thing reopens the step.
- **Reconcile needed something to read.** A reconciliation now records that it ran
  (`connection_reconciliation`: when, open lines, kinds that compared nothing) — nothing reaches
  the ledger. Only Connections whose venue states what is held count; with none, the step is
  optional.
- **Two-factor is listed, optional, and reads off.** Ticket 08 is not done, so there is no
  enrolment to read. When it lands, `services/first_run._two_factor` reads the enrolled secret
  and the step's sentence changes with it.
- **Generating a report had no screen.** The multi-year overview gained a Reports section: one
  row per Tax Year with its latest report, the appendix downloads, and a generate action that
  shows the API's own refusal sentence.
- **Empty and error states, across the app.** Every client request goes through one `request()`
  that names an unreachable API; a refusal without the API's own sentence now appends what to
  do; vague fallbacks ("The event…", "The pair…") name the thing; empty regions that named no
  next step gained one, with a link where a screen produces the data.

Not covered: a malformed API response inside a mutation still surfaces the schema parser's
message, and the display-rate notice asks for a reload rather than offering a retry.
