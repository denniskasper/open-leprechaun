# 09 — Statutory configuration store

**What to build:** Every statutory constant the tax engines will need lives as per-year configuration with a cited source, editable in settings. No engine reads it yet — this ticket makes the values exist and be maintainable so that later tickets never hardcode one.

**Blocked by:** 03, 02

**Status:** ready-for-agent

- [ ] Per-year rows cover: the private-sale exemption limit, the other-income exemption limit, the saver's allowance, the flat rate and solidarity surcharge, church-tax rates, per-category loss caps, and the annual base rate for advance lump sums
- [ ] Each value records the source it came from, shown in the UI
- [ ] Values are editable in settings and validated on entry
- [ ] Filing status and church-tax election are settings that select which per-year values apply
- [ ] A year with a required value unset is identifiable, so later tickets can refuse to compute it
- [ ] No statutory value appears as a literal in application logic
