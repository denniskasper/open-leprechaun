# 25 — Pre-flight blockers

**What to build:** The app refuses to finalise a report while it already knows something is wrong, and each blocker links to the screen that resolves it. The Admin may override, and the override is recorded on the report itself.

**Blocked by:** 23

**Status:** ready-for-agent

- [ ] Blockers include unmatched transfers, unpriced Instruments with activity in the year, lots with unresolved shortfalls, unacknowledged Instruments with activity, and missing statutory configuration for the year
- [ ] Later tickets can register further blockers without changing the finalisation flow
- [ ] Each blocker links to the screen that resolves it
- [ ] Finalisation is refused while any blocker is unresolved
- [ ] An override requires an acknowledgement, which is recorded on the report and shown wherever the report is
