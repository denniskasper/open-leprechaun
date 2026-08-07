# 40 — History windows and coverage warnings

**What to build:** The Admin is told how far back each venue can actually reach, so "no trades found" is never mistaken for "no trades exist".

**Blocked by:** 35

**Status:** ready-for-agent

- [ ] Each adapter declares its maximum lookback, shown per Connection in plain language
- [ ] After a sync, the result states the period actually covered
- [ ] The dashboard warns when a venue's coverage starts later than the earliest activity recorded elsewhere
- [ ] The warning names the venue and links to the import path that would close the gap
