# 42 — Scheduled tasks

**What to build:** Price updates, snapshots and syncs run on a schedule the Admin controls, and each records what happened.

**Blocked by:** 35

**Status:** done

- [x] Tasks are configurable in settings with a cron expression and can be individually enabled or disabled
- [x] Each task offers a manual run-now
- [x] Each task records last run, duration, outcome and error
- [x] Overlapping runs of the same task are prevented
- [x] A failing task is visible without opening logs

## Comments

Implemented as a cron reader (`services/cron.py`), the generic scheduling service
(`services/scheduled_tasks.py`) over one table (`scheduled_task`), the catalogue of shipped tasks
(`services/task_catalogue.py`), the background loop (`scheduler.py`, started by the served app),
three endpoints under `/scheduled-tasks`, one setting (`SCHEDULER_ENABLED`) and
`Settings → Scheduled tasks`.

- **Configurable, individually.** `PUT /scheduled-tasks/{key}` takes a five-field cron expression
  and an enabled flag. Tasks are declared in code; a row holds only what the Admin chose and what
  the last run did, so a task added later needs no migration. Cron is read on the Europe/Berlin
  clock; an expression that names no schedule is refused with the field at fault.
- **Run-now.** `POST /scheduled-tasks/{key}/run` runs synchronously and answers the task as the
  run left it — enabled or not.
- **Last run, duration, outcome, error.** A run stamps its start and clears the previous outcome,
  then states `ok` with a one-line summary or `failed` with a sentence. An unexpected exception is
  recorded by type only (ADR-0003).
- **No overlap.** A run holds a Postgres advisory lock on its own connection, across every
  process. A second run is refused (409 for run-now), never queued; a fire that fell due
  meanwhile is answered once afterwards. The lock dies with the process, so a crash leaves
  nothing stuck — a start with no finish and no lock reads as failed, "interrupted".
- **Failure without logs.** The settings screen opens with the failing tasks named and shows each
  task's error beside it.

Decisions worth recording:

- **Three tasks ship**: crypto price update, security price update, Connection sync — all enabled
  by default. The snapshot task belongs to ticket 54 and is one more catalogue entry.
- **When a price update fails**: only when a provider's own failure left an Instrument without a
  fresh price. An Instrument no provider knows is not a failure — it would fail the task forever.
- **Missed fires are answered once**, and a schedule counts forward from when it was last chosen
  or first seen by a scheduler — persisted, so frequent restarts cannot starve a long interval.
- **Own cron reader, no dependency**: five numeric fields, lists, ranges, steps; day-of-month and
  day-of-week together mean either. A wall time the clock change skips does not fire that day;
  one it repeats fires once.
- **`next_due_at` is already served** — ticket 55 reads it; nothing more is needed there.
- **Left for later**: the screen does not say when `SCHEDULER_ENABLED` is off on this instance;
  no failure signal outside this screen (ticket 55); the panel does not yet follow ticket 60's
  settings convention, which does not exist yet.
