import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// A screen under Settings is one panel (docs/agents/design.md, "Settings
// panels"): it renders through `SettingsPanel`, which draws the page header
// itself, so the screen never opens with a `PageHeader` of its own.

function read(path: string): string {
  return readFileSync(fileURLToPath(new URL(`../src/${path}`, import.meta.url)), "utf8");
}

/** Every `/settings/<panel>` the navigation declares, by its panel name. */
const PANELS = [...read("navigation.ts").matchAll(/to: "\/settings\/([a-z-]+)"/g)].map(
  ([, panel]) => panel!,
);

it("finds the Settings panels in the navigation", () => {
  expect(PANELS).toEqual(expect.arrayContaining(["platforms", "security"]));
});

describe.each(PANELS)("/settings/%s", (panel) => {
  const source = read(`pages/${panel}.tsx`);

  it("renders through SettingsPanel", () => {
    expect(/<SettingsPanel\b/.test(source)).toBe(true);
  });

  it("leaves the page header to the panel", () => {
    expect(source.includes("@/components/page-header")).toBe(false);
  });

  it("sets its content in named groups", () => {
    expect(/<SettingsGroup\b/.test(source)).toBe(true);
  });
});
