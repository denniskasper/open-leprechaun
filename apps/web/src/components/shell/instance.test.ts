import { describe, expect, it } from "vitest";
import { badgeLabel, versionLabel } from "./instance";

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

describe("versionLabel", () => {
  it("shows a development instance its bare commit hash", () => {
    expect(versionLabel({ environment: "development", version: "55d554f" })).toBe("55d554f");
  });

  it("names a production release with a v", () => {
    expect(versionLabel({ environment: "production", version: "0.1.0" })).toBe("v0.1.0");
  });

  it("does not double the v when the deployment already wrote one", () => {
    expect(versionLabel({ environment: "production", version: "v0.1.0" })).toBe("v0.1.0");
  });

  it("shows nothing before the API has identified the instance", () => {
    expect(versionLabel(undefined)).toBeNull();
  });
});
