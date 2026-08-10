# 31 — Import framework

**What to build:** Every import shows exactly what it will create before it creates anything, commits as a separate act, records itself as a batch, and can be reversed as a unit. Re-importing the same file changes nothing.

**Blocked by:** 13

**Status:** ready-for-agent

- [x] Preview lists rows to be created, rows skipped with reasons, Instruments to be auto-created, and warnings — before any write
- [x] Nothing is written during preview; confirmation is a separate call
- [x] Every import is recorded as a batch and is reversible as a unit
- [x] Deduplication is keyed on source and external identifier; re-import is idempotent
- [x] The preview states how many rows would be duplicates
- [x] Exactly one authoritative ingestion mode is declared per Account; a second source may reconcile but may not write
- [x] An imported row edited or deleted by hand is marked as manually overridden, and a re-import does not silently revert it
- [x] Bulk reassignment of Account and bulk re-typing of rows are available

## Comments

Implemented. One revision (`4d7e91c3a8b2`) creates `import_batch` and `imported_row` and puts
`authoritative_source` on `account`; the one evaluation the preview and the commit share lives
in `services/imports.py`, the batch and registry writes in `repositories/imports.py`.

How each criterion is held:

- **Preview lists everything**: `evaluate` judges every row — creatable, skipped with the same
  sentences a hand-recorded event would get (`structural_defect` now judges any leg-shaped
  object via a `LegShape` protocol), Instruments to auto-create resolved by the ledger's own
  identity attributes (chain+contract, symbol, ISIN via the identifier history), and warnings
  (unacknowledged auto-creations, the authoritative-source consequence). A test pins that a
  preview changes no table row count and no Account column.
- **Confirmation is a separate call**: `POST /imports/preview` vs `POST /imports`. The commit
  re-runs the same evaluation server-side — nothing trusts a client echo of the preview — and
  writes batch, Transactions and registry rows in one database transaction.
- **A batch, reversible as a unit**: `DELETE /import-batches/{id}` removes what the batch
  created; the `/imports` screen lists batches with row counts and a two-press Reverse.
- **Dedup on (source, external_id)**: a unique constraint on the `imported_row` registry is the
  arbiter; re-import skips registered ids at evaluation, and a racing duplicate loses cleanly at
  write (`ON CONFLICT DO NOTHING`, the orphan Transaction deleted in the same DB transaction).
  A pure re-import records **no batch** — deliberately, so re-running a file changes nothing.
- **Duplicate count**: the preview answers `duplicates` plus the ids themselves.
- **One authoritative source per Account**: the first commit claims
  `account.authoritative_source` under `FOR UPDATE`; a different source may always preview
  (reconcile) but its commit is refused 409 with a sentence naming the holder. The Admin can
  declare or clear the source explicitly (`PUT /accounts/{id}/authoritative-source`) — the
  escape hatch for migrating an Account to a different ingestion mode.
- **Manual override**: the ledger's own edit, delete, and both bulk acts mark the registry row
  `overridden`. A deleted row leaves a tombstone (`transaction_id` SET NULL) so its dedup key
  survives; CHECKs pin that a registry row detached from its batch or Transaction is only ever
  an overridden tombstone. Reversal spares overridden rows — the Admin took ownership — and
  detaches their tombstones so a later re-import still counts them duplicates.
- **Bulk repair**: `POST /transactions/bulk-reassignment` moves every leg of the chosen events
  to another Account; `POST /transactions/bulk-retyping` re-types them, each judged first by
  `retype_all` in the service (the same structural and declaration sentences), all-or-nothing.
  The ledger screen grew a checkbox column and a Bulk repair toolbar; a Playwright spec drives
  import → marker → bulk re-type → reversal-sparing-the-override through the real browser.

Decisions worth recording:

- **The registry outlives the batch and the Transaction.** `imported_row` is the durable fact;
  batch reversal cascades only the non-overridden rows away. This is what makes "reversible as
  a unit" and "a re-import does not silently revert my correction" compatible.
- **An import writes into exactly one Account** (the batch carries it); legs inherit it. A file
  spanning accounts is a later connector's problem to split; bulk reassignment repairs the
  wrong choice.
- **No opening balances by import**: the declaration is the Admin's to own, so the evaluation
  refuses the type with the declaration's own sentence.
- **Instruments auto-created by a commit survive its reversal** — they may already be referenced
  elsewhere, and an unacknowledged Instrument standing idle is the inbox's normal state.
  Instrument creation sits just outside the batch's database transaction (the unique indexes
  arbitrate races); the batch, its Transactions and registry rows land atomically.
- **Preview/commit UI arrives with the connectors** (32, 33, 35): ticket 31 ships the `/imports`
  batches screen, the ledger provenance markers and the bulk toolbar; nothing can parse a file
  yet, so the preview flow is exercised over the API.
- No version bump — releases have not started; like tickets 10–30 this rides as `feat:`.
- Post-review fixes (two-axis review): the bulk re-type judgement moved out of the router into
  `services/transactions.retype_all`; commit refusals now carry their sentence from the service
  (`CommitRefused`), so the router neither re-composes the 409 sentence nor re-queries the
  Account (a crash on a vanished Account); `external_id` got its own payload type instead of
  wearing `Source`; the instrument-spec payload maps by `model_dump` instead of `getattr`
  reflection.
