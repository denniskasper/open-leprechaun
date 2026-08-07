# 31 — Import framework

**What to build:** Every import shows exactly what it will create before it creates anything, commits as a separate act, records itself as a batch, and can be reversed as a unit. Re-importing the same file changes nothing.

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] Preview lists rows to be created, rows skipped with reasons, Instruments to be auto-created, and warnings — before any write
- [ ] Nothing is written during preview; confirmation is a separate call
- [ ] Every import is recorded as a batch and is reversible as a unit
- [ ] Deduplication is keyed on source and external identifier; re-import is idempotent
- [ ] The preview states how many rows would be duplicates
- [ ] Exactly one authoritative ingestion mode is declared per Account; a second source may reconcile but may not write
- [ ] An imported row edited or deleted by hand is marked as manually overridden, and a re-import does not silently revert it
- [ ] Bulk reassignment of Account and bulk re-typing of rows are available
