import { describe, expect, it } from "vitest";
import type { ScheduledTask } from "@/api/scheduled-tasks";
import {
  describeDuration,
  describeNextDue,
  describeStatus,
  failingTasks,
  taskTone,
} from "./scheduled-tasks";

function task(overrides: Partial<ScheduledTask> = {}): ScheduledTask {
  return {
    key: "crypto_prices",
    name: "Crypto price update",
    description: "Prices every crypto Instrument through the provider chain.",
    cron: "*/15 * * * *",
    enabled: true,
    running: false,
    last_started_at: "2026-10-03T09:15:00Z",
    last_finished_at: "2026-10-03T09:15:02Z",
    duration_seconds: 2,
    outcome: "ok",
    error: null,
    detail: "4 fresh, 0 stale, 0 unpriced.",
    next_due_at: "2026-10-03T09:30:00Z",
    ...overrides,
  };
}

const NEVER_RUN = {
  last_started_at: null,
  last_finished_at: null,
  duration_seconds: null,
  outcome: null,
  detail: null,
};

describe("taskTone", () => {
  it("wears the alarm colour for a failed last run", () => {
    expect(taskTone(task({ outcome: "failed", error: "Down." }))).toBe("alarm");
  });

  it("wears the signal colour for a good last run", () => {
    expect(taskTone(task())).toBe("signal");
  });

  it("is in caution while a run is in flight, whatever came before", () => {
    expect(taskTone(task({ running: true, outcome: null }))).toBe("caution");
  });

  it("is idle before the first run", () => {
    expect(taskTone(task(NEVER_RUN))).toBe("idle");
  });

  it("keeps a failure in alarm on a disabled task", () => {
    expect(taskTone(task({ enabled: false, outcome: "failed", error: "Down." }))).toBe("alarm");
  });
});

describe("describeStatus", () => {
  it("names each state in a word", () => {
    expect(describeStatus(task())).toBe("Succeeded");
    expect(describeStatus(task({ outcome: "failed", error: "Down." }))).toBe("Failed");
    expect(describeStatus(task({ running: true, outcome: null }))).toBe("Running");
    expect(describeStatus(task(NEVER_RUN))).toBe("Never run");
  });
});

describe("describeDuration", () => {
  it("says so when no run has finished", () => {
    expect(describeDuration(null)).toBe("—");
  });

  it("keeps short runs in fractions of a second", () => {
    expect(describeDuration(0.042, "en-GB")).toBe("0.04 s");
    expect(describeDuration(2, "en-GB")).toBe("2 s");
  });

  it("splits longer runs into minutes and seconds", () => {
    expect(describeDuration(61.4, "en-GB")).toBe("1 min 1 s");
    expect(describeDuration(3725, "en-GB")).toBe("62 min 5 s");
  });
});

describe("describeNextDue", () => {
  const now = Date.parse("2026-10-03T09:20:00Z");

  it("says a disabled task is not scheduled", () => {
    expect(describeNextDue(task({ enabled: false, next_due_at: null }), now)).toBe("Not scheduled");
  });

  it("says a fire already past is due now", () => {
    expect(describeNextDue(task({ next_due_at: "2026-10-03T09:15:00Z" }), now)).toBe("Due now");
  });

  it("states the instant of a fire still ahead", () => {
    expect(describeNextDue(task(), now, "en-GB", "UTC")).toBe("3 Oct 2026, 09:30:00");
  });
});

describe("failingTasks", () => {
  it("names only the tasks whose last run failed", () => {
    const failed = task({ key: "connection_sync", outcome: "failed", error: "Down." });

    expect(failingTasks([task(), failed, task(NEVER_RUN)])).toEqual([failed]);
  });
});
