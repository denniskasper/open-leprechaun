# 56 — Ledger export for independent verification

**What to build:** The Admin can hand their clean ledger to an independent tax tool and have it compute the same year from identical transactions — so a disagreement between two engines is a disagreement about rules, not about data.

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] The ledger exports in an independent tool's documented import format
- [ ] Every transaction type in the vocabulary maps to something in that format, or is reported as unmappable rather than silently dropped
- [ ] The export is deterministic: the same ledger produces the same file
- [ ] Data flows outward only; nothing is ever imported back from that tool
- [ ] The export carries no more than the tool needs
