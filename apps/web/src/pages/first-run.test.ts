import { describe, expect, it } from "vitest";
import type { ChecklistItem } from "@/api/first-run";
import { NAV_SECTIONS } from "@/navigation";
import { nextStep, progress, STEPS } from "@/pages/first-run";

function item(key: ChecklistItem["key"], overrides: Partial<ChecklistItem> = {}): ChecklistItem {
  return { key, done: false, optional: false, detail: "", resolve_path: "/", ...overrides };
}

describe("progress", () => {
  it("counts only the steps the walk cannot finish without", () => {
    const items = [
      item("password", { done: true }),
      item("two_factor", { optional: true }),
      item("platforms_and_accounts", { done: true }),
      item("report"),
    ];

    expect(progress(items)).toEqual({ done: 2, required: 3 });
  });

  it("does not count an optional step that happens to be done", () => {
    expect(progress([item("two_factor", { optional: true, done: true }), item("report")])).toEqual({
      done: 0,
      required: 1,
    });
  });
});

describe("nextStep", () => {
  it("is the first open step, passing over what is done and what is optional", () => {
    const items = [
      item("password", { done: true }),
      item("two_factor", { optional: true }),
      item("platforms_and_accounts"),
      item("connect_or_import"),
    ];

    expect(nextStep(items)).toBe("platforms_and_accounts");
  });

  it("is nothing once only optional steps stay open", () => {
    expect(nextStep([item("password", { done: true }), item("two_factor", { optional: true })])).toBe(
      null,
    );
  });
});

describe("STEPS", () => {
  it("offers a second way only to a screen navigation declares", () => {
    const declared = NAV_SECTIONS.flatMap((section) => section.items.map((entry) => entry.to));

    for (const step of Object.values(STEPS)) {
      if (step.alternative) {
        expect(declared).toContain(step.alternative.to);
      }
    }
  });
});
