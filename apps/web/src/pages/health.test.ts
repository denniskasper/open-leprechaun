import { describe, expect, it } from "vitest";
import type { HealthReport } from "@/api/health";
import { describeProvider, problemsOf, providerTone, toVerdict } from "./health";

type Provider = HealthReport["providers"][number];
type Connection = HealthReport["connections"][number];
type Task = HealthReport["tasks"][number];

function provider(overrides: Partial<Provider> = {}): Provider {
  return {
    name: "coingecko",
    feeds: "crypto_prices",
    state: "ok",
    last_success_at: "2026-10-04T08:45:00Z",
    last_error_at: null,
    last_error: null,
    affected_instruments: [],
    ...overrides,
  };
}

function connection(kinds: Connection["kinds"] = []): Connection {
  return { id: 3, label: "Main account", venue: "okx", last_sync_at: null, kinds };
}

function task(overrides: Partial<Task> = {}): Task {
  return {
    key: "crypto_prices",
    name: "Crypto price update",
    enabled: true,
    running: false,
    last_started_at: "2026-10-04T09:00:00Z",
    last_finished_at: "2026-10-04T09:00:02Z",
    outcome: "ok",
    error: null,
    next_due_at: "2026-10-04T09:15:00Z",
    ...overrides,
  };
}

function report(overrides: Partial<HealthReport> = {}): HealthReport {
  return {
    checked_at: "2026-10-04T09:00:00Z",
    providers: [provider(), provider({ name: "defillama" })],
    connections: [],
    tasks: [task()],
    scheduler_enabled: true,
    storage: {
      database_bytes: 52428800,
      crypto_daily_closes: 1200,
      security_daily_closes: 300,
      reference_rates: 90,
    },
    ...overrides,
  };
}

const KAS = { id: 7, symbol: "KAS", name: "Kaspa" };

describe("problemsOf", () => {
  it("finds nothing wrong when everything answered", () => {
    expect(problemsOf(report())).toEqual([]);
  });

  it("does not count a provider nothing has asked yet", () => {
    const quiet = report({
      providers: [provider({ state: "never_asked", last_success_at: null })],
    });

    expect(problemsOf(quiet)).toEqual([]);
  });

  it("names one failing provider and the Instruments it affects — and nothing else", () => {
    const problems = problemsOf(
      report({
        providers: [
          provider(),
          provider({
            name: "defillama",
            state: "outage",
            last_error: "defillama answered HTTP 502.",
            affected_instruments: [KAS],
          }),
        ],
      }),
    );

    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatchObject({
      tone: "alarm",
      title: "defillama is not answering",
      instruments: [KAS],
      to: "/settings/scheduled-tasks",
    });
    expect(problems[0]?.detail).toContain("defillama answered HTTP 502.");
    expect(problems[0]?.detail).toContain("1 Instrument has no fresh price");
  });

  it("calls a rate limit a rate limit, and a matter of waiting", () => {
    const [problem] = problemsOf(
      report({
        providers: [
          provider({
            state: "rate_limited",
            last_error: "coingecko asked for a pause (HTTP 429).",
            affected_instruments: [KAS, { id: 8, symbol: "BTC", name: "Bitcoin" }],
          }),
        ],
      }),
    );

    expect(problem).toMatchObject({ tone: "caution", title: "coingecko is rate-limiting" });
    expect(problem?.title).not.toMatch(/not answering|outage/i);
    expect(problem?.detail).toContain("2 Instruments have no fresh price");
  });

  it("says so when a failing provider left nothing stale", () => {
    const [problem] = problemsOf(
      report({ providers: [provider({ state: "outage", last_error: "Unreachable." })] }),
    );

    expect(problem).toMatchObject({ tone: "caution", instruments: [] });
    expect(problem?.detail).toContain("No Instrument is stale because of it");
  });

  it("says what a failing reference-rate source holds up instead of naming Instruments", () => {
    const [problem] = problemsOf(
      report({
        providers: [
          provider({
            name: "ecb",
            feeds: "reference_rates",
            state: "outage",
            last_error: "ecb failed with ConnectError.",
          }),
        ],
      }),
    );

    expect(problem?.tone).toBe("alarm");
    expect(problem?.detail).toContain("foreign-currency");
  });

  it("names the failing adapter kind of a Connection and sends the Admin to Connections", () => {
    const problems = problemsOf(
      report({
        connections: [
          connection([
            {
              adapter_kind: "spot",
              ok: true,
              last_success_at: "2026-10-04T06:00:00Z",
              last_error_at: null,
              last_error: null,
            },
            {
              adapter_kind: "futures",
              ok: false,
              last_success_at: "2026-10-03T06:00:00Z",
              last_error_at: "2026-10-04T06:00:00Z",
              last_error: "The venue refused the key.",
            },
          ]),
        ],
      }),
    );

    expect(problems).toEqual([
      expect.objectContaining({
        tone: "alarm",
        title: "Main account: futures failed",
        detail: "The venue refused the key.",
        to: "/settings/connections",
      }),
    ]);
  });

  it("names a task whose last run failed, but not one that is running again", () => {
    const failed = { outcome: "failed" as const, error: "coingecko is not answering." };

    expect(problemsOf(report({ tasks: [task(failed)] }))).toEqual([
      expect.objectContaining({
        tone: "alarm",
        title: "Crypto price update failed on its last run",
        detail: "coingecko is not answering.",
        to: "/settings/scheduled-tasks",
      }),
    ]);
    expect(problemsOf(report({ tasks: [task({ ...failed, running: true })] }))).toEqual([]);
  });

  it("gives every problem a screen that resolves it", () => {
    const problems = problemsOf(
      report({
        providers: [provider({ state: "outage", last_error: "Down." })],
        connections: [
          connection([
            {
              adapter_kind: "spot",
              ok: false,
              last_success_at: null,
              last_error_at: "2026-10-04T06:00:00Z",
              last_error: "Refused.",
            },
          ]),
        ],
        tasks: [task({ outcome: "failed", error: "Failed." })],
      }),
    );

    expect(problems).toHaveLength(3);
    for (const problem of problems) {
      expect(problem.to).toMatch(/^\/settings\/[a-z-]+$/);
      expect(problem.action).not.toBe("");
    }
  });
});

describe("toVerdict", () => {
  it("is idle until a report arrives", () => {
    expect(toVerdict(undefined)).toMatchObject({ tone: "idle", headline: "Checking" });
  });

  it("is operational when nothing is wrong", () => {
    expect(toVerdict([])).toMatchObject({ tone: "signal", headline: "Operational" });
  });

  it("counts the problems and never calls them an outage of everything", () => {
    const [one] = problemsOf(
      report({ providers: [provider({ state: "outage", affected_instruments: [KAS] })] }),
    );
    const verdict = toVerdict(one ? [one] : []);

    expect(verdict.headline).toBe("1 problem");
    expect(verdict.tone).toBe("alarm");
    expect(verdict.detail).toContain("Everything not named below");
  });

  it("stays in caution while every problem is one to wait out", () => {
    const problems = problemsOf(
      report({
        providers: [
          provider({ state: "rate_limited" }),
          provider({ name: "defillama", state: "rate_limited" }),
        ],
      }),
    );

    expect(toVerdict(problems)).toMatchObject({ tone: "caution", headline: "2 problems" });
  });
});

describe("providerTone and describeProvider", () => {
  it("pairs each state with its own word and colour", () => {
    expect([
      [providerTone(provider()), describeProvider(provider())],
      [
        providerTone(provider({ state: "rate_limited" })),
        describeProvider(provider({ state: "rate_limited" })),
      ],
      [
        providerTone(provider({ state: "outage" })),
        describeProvider(provider({ state: "outage" })),
      ],
      [
        providerTone(provider({ state: "never_asked" })),
        describeProvider(provider({ state: "never_asked" })),
      ],
    ]).toEqual([
      ["signal", "Answering"],
      ["caution", "Rate-limited"],
      ["alarm", "Not answering"],
      ["idle", "Not asked yet"],
    ]);
  });
});
