import { describe, expect, it } from "vitest";
import { badgeLabel } from "./instance";

describe("badgeLabel", () => {
  it("labels a development instance", () => {
    expect(badgeLabel({ environment: "development", version: "a17a9a2" })).toBe("dev");
  });

  it("shows nothing within production", () => {
    expect(badgeLabel({ environment: "production", version: "2026.08.1" })).toBeNull();
  });

  it("shows nothing before the API has identified the instance", () => {
    expect(badgeLabel(undefined)).toBeNull();
  });
});
