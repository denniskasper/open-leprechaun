# 23 — Report lifecycle and staleness

**What to build:** Generating a report freezes its figures together with a fingerprint of the inputs that produced them. A report moves from draft to final, a final report never changes, and the Admin is told when the data underneath one has moved.

**Blocked by:** 21, 22

**Status:** ready-for-agent

- [ ] Generating a report stores the computed figures and a fingerprint of the inputs
- [ ] A report moves draft → final; a final report is immutable
- [ ] Regenerating creates a new report and never mutates an existing one
- [ ] A report whose fingerprint no longer matches current data is flagged stale wherever it is shown
- [ ] The staleness notice names what changed, by input class and count
- [ ] The fingerprint covers statutory configuration, so correcting a rate marks dependent reports stale
- [ ] A final report is never silently recomputed; regeneration is an explicit action
- [ ] Deleting a transaction a final report depends on is blocked with an explanation, or marks the report stale — never silently changes a finalised figure
