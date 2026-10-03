import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchScheduledTasks, runScheduledTask, setSchedule } from "./scheduled-tasks";

const task = {
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
};

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchScheduledTasks", () => {
  it("reads every task with its schedule and last run", async () => {
    respondWith(200, [task]);

    await expect(fetchScheduledTasks()).resolves.toEqual([task]);

    expect(fetch).toHaveBeenCalledWith("/api/scheduled-tasks");
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchScheduledTasks()).rejects.toThrow("500");
  });

  it("rejects an outcome outside the two the API states", async () => {
    respondWith(200, [{ ...task, outcome: "maybe" }]);

    await expect(fetchScheduledTasks()).rejects.toThrow();
  });
});

describe("setSchedule", () => {
  it("puts the cron expression and the enabled flag for one task", async () => {
    respondWith(200, { ...task, cron: "0 * * * *", enabled: false, next_due_at: null });

    await expect(
      setSchedule("crypto_prices", { cron: "0 * * * *", enabled: false }),
    ).resolves.toMatchObject({ cron: "0 * * * *", enabled: false });

    expect(fetch).toHaveBeenCalledWith("/api/scheduled-tasks/crypto_prices", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cron: "0 * * * *", enabled: false }),
    });
  });

  it("carries the API's own words for a refused expression", async () => {
    respondWith(422, { detail: "The hour field runs from 0 to 23; '24' does not." });

    await expect(setSchedule("crypto_prices", { cron: "0 24 * * *", enabled: true })).rejects.toThrow(
      "The hour field runs from 0 to 23; '24' does not.",
    );
  });
});

describe("runScheduledTask", () => {
  it("posts the run and answers the task as the run left it", async () => {
    respondWith(200, { ...task, outcome: "failed", error: "coingecko is not answering." });

    await expect(runScheduledTask("crypto_prices")).resolves.toMatchObject({
      outcome: "failed",
      error: "coingecko is not answering.",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/scheduled-tasks/crypto_prices/run",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("carries the API's own words when the task is already running", async () => {
    respondWith(409, { detail: "Crypto price update is already running." });

    await expect(runScheduledTask("crypto_prices")).rejects.toThrow(
      "Crypto price update is already running.",
    );
  });
});
