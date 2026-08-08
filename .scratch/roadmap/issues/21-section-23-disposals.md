# 21 — §23 disposals

**What to build:** Crypto disposals are matched against acquisitions FIFO within the Account that held them, holding periods decide exemption, and the annual all-or-nothing limit is applied from configuration rather than from constants in logic.

**Blocked by:** 19, 09

**Status:** ready-for-agent

- [ ] Disposals consume lots FIFO within the same Account and Instrument
- [ ] Each consumption records quantity, basis, proceeds, holding period in days and a long-term flag
- [ ] A disposal exceeding available lots is a hard error naming the shortfall, never a silent zero-basis fill
- [ ] Disposals held beyond the statutory period are exempt, excluded from the total, and still visible in detail
- [ ] The holding period is computed between absolute instants and is unaffected by timezone
- [ ] A self-transfer does not restart the holding period
- [ ] The exemption limit is read per year from configuration; below it the whole amount is free, at or above it the full amount is taxable
- [ ] Headroom or overshoot against the limit is stated explicitly
- [ ] The tax year is bucketed by German local date while timestamps remain absolute instants
- [ ] Tests name the paragraph each rule implements; boundary cases are tested at, just below and just above every threshold, and on both sides of a year boundary in winter and summer time
