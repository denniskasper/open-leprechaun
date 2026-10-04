import { describe, expect, it } from "vitest";
import { NAV_SECTIONS, SETTINGS_INDEX } from "./navigation";

describe("the Settings section", () => {
  const settings = NAV_SECTIONS.find((section) => section.label === "Settings");

  it("registers the Security panel", () => {
    expect(settings?.items).toContainEqual(
      expect.objectContaining({ to: "/settings/security", label: "Security" }),
    );
  });

  it("keeps every panel under /settings", () => {
    for (const item of settings?.items ?? []) {
      expect(item.to).toMatch(/^\/settings\/[a-z-]+$/);
    }
  });

  it("sends a bare /settings to its first panel, not to an index", () => {
    expect(SETTINGS_INDEX).toBe("/settings/platforms");
  });
});
