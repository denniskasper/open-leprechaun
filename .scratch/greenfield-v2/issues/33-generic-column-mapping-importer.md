# 33 — Generic column-mapping importer

**What to build:** An unsupported venue does not block the Admin. Map an arbitrary file's columns onto ledger fields, see the first rows interpreted live, then save the mapping under a name and reuse it.

**Blocked by:** 31

**Status:** ready-for-agent

- [ ] The mapping UI shows a live preview of the first rows as they would be interpreted
- [ ] Required fields are enforced before the import can proceed
- [ ] Ambiguous dates require an explicit format and timezone; nothing is guessed
- [ ] A mapping can be saved, named and reused against a later file
- [ ] The result flows through the same preview, batch and reversal machinery as any other import
