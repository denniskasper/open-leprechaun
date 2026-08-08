# 30 — Aggregates: bots and dust sweeps

**What to build:** Two cases where thousands of tiny records would otherwise drown the ledger: a bot-run strategy, and a venue sweeping many dust balances into one coin. Both are summarised as an aggregate whose constituents remain retrievable, and neither changes a figure.

**Blocked by:** 28

**Status:** ready-for-agent

- [ ] A bot's activity is summarised as an aggregate with its constituent fills retrievable
- [ ] The capital-income figure from an aggregate equals the sum over its constituents
- [ ] A dust sweep is recorded as one aggregate disposal into the received Instrument, with constituents retrievable
- [ ] Each constituent disposal still consumes its lots correctly
- [ ] No disposal is suppressed from the totals — only from the summary presentation
