import { describe, expect, it } from "vitest";
import { badgeLabel, hostLabel, versionLabel } from "./instance";

describe("badgeLabel", () => {
  it("labels a development instance", () => {
    expect(badgeLabel({ environment: "development", version: "a17a9a2", host: null })).toBe("dev");
  });

  it("shows nothing within production", () => {
    expect(badgeLabel({ environment: "production", version: "2026.08.1", host: null })).toBeNull();
  });

  it("shows nothing before the API has identified the instance", () => {
    expect(badgeLabel(undefined)).toBeNull();
  });
});

describe("versionLabel", () => {
  it("shows a development instance its bare commit hash", () => {
    expect(versionLabel({ environment: "development", version: "55d554f", host: null })).toBe("55d554f");
  });

  it("names a production release with a v", () => {
    expect(versionLabel({ environment: "production", version: "0.1.0", host: null })).toBe("v0.1.0");
  });

  it("does not double the v when the deployment already wrote one", () => {
    expect(versionLabel({ environment: "production", version: "v0.1.0", host: null })).toBe("v0.1.0");
  });

  it("shows nothing before the API has identified the instance", () => {
    expect(versionLabel(undefined)).toBeNull();
  });
});

describe("hostLabel", () => {
  it("names the machine a development instance runs on", () => {
    expect(hostLabel({ environment: "development", version: "a17a9a2", host: "tp-x1-yoga" })).toBe(
      "tp-x1-yoga",
    );
  });

  it("names nothing when the API states no machine", () => {
    expect(hostLabel({ environment: "development", version: "a17a9a2", host: null })).toBeNull();
  });

  it("names nothing within production, whatever arrives", () => {
    expect(hostLabel({ environment: "production", version: "0.1.0", host: "web-1" })).toBeNull();
  });

  it("names nothing before the API has identified the instance", () => {
    expect(hostLabel(undefined)).toBeNull();
  });
});
