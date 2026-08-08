# 32 — CSV connector port; Ledger and BitBox

**What to build:** The port for importing a venue's exported file, proven by two real hardware-wallet connectors. Each declares the file it expects, the timezone it exports in, and the units it uses — because an export in local time silently produces wrong tax years, and one in sub-units silently produces wrong quantities.

**Blocked by:** 31

**Status:** ready-for-agent

- [ ] A connector port with a fake, plus a registry so adding one touches no service, router or screen
- [ ] Two hardware-wallet connectors ship and work end to end through preview and commit
- [ ] Each connector declares the file it expects and rejects a mismatched file with a clear message rather than mis-parsing it
- [ ] Each connector declares its venue's timezone and converts to UTC; an export in local time is never tagged UTC
- [ ] Each connector declares its units and normalises them; a sub-unit export is never taken as a whole unit
- [ ] A connector that cannot support a variant refuses that file explicitly
- [ ] Connectors are tested against recorded fixtures, with no live calls in CI
- [ ] The timezone and unit handling of each connector is tested explicitly
