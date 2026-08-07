# 42 — Scheduled tasks

**What to build:** Price updates, snapshots and syncs run on a schedule the Admin controls, and each records what happened.

**Blocked by:** 35

**Status:** ready-for-agent

- [ ] Tasks are configurable in settings with a cron expression and can be individually enabled or disabled
- [ ] Each task offers a manual run-now
- [ ] Each task records last run, duration, outcome and error
- [ ] Overlapping runs of the same task are prevented
- [ ] A failing task is visible without opening logs
