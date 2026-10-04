import { afterEach, describe, expect, it, vi } from "vitest";
import { appendixUrl, fetchReports, generateReport } from "./reports";

const report = {
  id: 4,
  year: 2025,
  status: "draft",
  generated_at: "2026-10-04T09:00:00Z",
  stale: false,
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

describe("fetchReports", () => {
  it("reads each report's year, lifecycle and staleness", async () => {
    respondWith(200, [{ ...report, finalised_at: null, changed_inputs: [] }]);

    await expect(fetchReports()).resolves.toEqual([report]);

    expect(fetch).toHaveBeenCalledWith("/api/reports");
  });

  it("rejects an error status, naming what was not answered", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchReports()).rejects.toThrow("The API answered 500 instead of the reports.");
  });
});

describe("generateReport", () => {
  it("asks for the Tax Year and answers the new report's id", async () => {
    respondWith(201, { id: 7 });

    await expect(generateReport(2025)).resolves.toBe(7);

    expect(fetch).toHaveBeenCalledWith(
      "/api/reports",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ year: 2025 }) }),
    );
  });

  it("passes on the API's own sentence for a year it cannot state", async () => {
    respondWith(409, { detail: "No private_sale_exemption_limit is configured for 2025." });

    await expect(generateReport(2025)).rejects.toThrow(
      "No private_sale_exemption_limit is configured for 2025.",
    );
  });

  it("names the year and what to do when the API gave no reason", async () => {
    respondWith(500, {});

    await expect(generateReport(2025)).rejects.toThrow(
      /^The 2025 report could not be generated\. .*try again\.$/,
    );
  });
});

describe("appendixUrl", () => {
  it("points at the report's appendix in the asked format", () => {
    expect(appendixUrl(7, "pdf")).toBe("/api/reports/7/appendix.pdf");
    expect(appendixUrl(7, "csv")).toBe("/api/reports/7/appendix.csv");
  });
});
