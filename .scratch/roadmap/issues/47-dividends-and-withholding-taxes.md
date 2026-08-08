# 47 — Dividends, distributions and withholding taxes

**What to build:** Income from securities is recorded gross with every tax already taken out of it, so the Admin can see both what is taxable and what has already been paid — and to whom.

**Blocked by:** 46

**Status:** ready-for-agent

- [ ] Each dividend records gross, foreign withholding with its source country, German tax withheld at source split into its components, and net received
- [ ] Foreign withholding is reported as creditable up to the treaty limit, with any excess shown as reclaimable from the source country rather than creditable
- [ ] The app reports creditability; it never pursues a reclaim
- [ ] A fund distribution carries its partial exemption before entering its category
- [ ] Income from a withholding broker is distinguished from income that must still be declared
- [ ] Interest is recorded and routed to the other-income category
- [ ] Each event emits a Section 20 Event and computes no tax itself
