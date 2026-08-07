# 15 — Opening Balance, both variants

**What to build:** A position that predates available history can be recorded honestly, and the record distinguishes what is known from what is reconstructed. This matters because an exemption depends on the acquisition date, while the basis may be a genuine estimate.

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] An Opening Balance behaves like an inbound transfer but marks its minted lot as estimated
- [ ] The two cases are distinct: acquisition date known with basis estimated, and both reconstructed
- [ ] Conservative dating is recommended only where the date is genuinely unknown, and the UI explains why
- [ ] Where the date is known, the Admin supplies it and it is used as given
- [ ] Any later disposal consuming such a lot is flagged as resting on an estimate
- [ ] The UI states plainly which figures the choice will affect
