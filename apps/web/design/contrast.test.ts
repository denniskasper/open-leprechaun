import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { wcagContrast } from "culori";
import { describe, expect, it } from "vitest";

// The ticket's claim, held as a test: both themes meet WCAG AA. The tokens live
// in CSS, so the test reads them from CSS — a colour tuned later is re-judged
// here, not trusted.

const css = readFileSync(fileURLToPath(new URL("../src/index.css", import.meta.url)), "utf8");

function themeTokens(selector: string): Map<string, string> {
  const block = css.match(new RegExp(`${selector.replace(".", "\\.")}\\s*\\{([^}]*)\\}`))?.[1];
  if (!block) throw new Error(`No ${selector} block found in index.css`);

  const tokens = new Map<string, string>();
  for (const [, name, value] of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    if (name !== undefined && value !== undefined) tokens.set(name, value.trim());
  }
  return tokens;
}

function resolve(tokens: Map<string, string>, name: string): string {
  const value = tokens.get(name);
  if (!value) throw new Error(`Token ${name} is not defined`);
  const reference = value.match(/^var\((--[\w-]+)\)$/);
  return reference?.[1] !== undefined ? resolve(tokens, reference[1]) : value;
}

// Text on its surface needs 4.5:1; large text and non-text indicators need 3:1.
const TEXT_PAIRS: [foreground: string, background: string][] = [
  ["--foreground", "--background"],
  ["--muted-foreground", "--background"],
  ["--foreground", "--card"],
  ["--muted-foreground", "--card"],
  ["--foreground", "--popover"],
  ["--foreground", "--muted"],
  ["--primary-foreground", "--primary"],
  ["--secondary-foreground", "--secondary"],
  ["--accent-foreground", "--accent"],
  // Muted text also sits on hover/active tints (nav items, menu items).
  ["--muted-foreground", "--accent"],
  ["--muted-foreground", "--secondary"],
  ["--destructive-foreground", "--destructive"],
  ["--signal", "--background"],
  ["--caution", "--background"],
  ["--alarm", "--background"],
];

const INDICATOR_PAIRS: [foreground: string, background: string][] = [
  ["--ring", "--background"],
  ["--primary", "--background"],
];

describe.each([
  ["light", ":root"],
  ["dark", ".dark"],
])("the %s theme", (_name, selector) => {
  const tokens = themeTokens(selector);

  it.each(TEXT_PAIRS)("renders %s on %s at AA text contrast", (fg, bg) => {
    expect(wcagContrast(resolve(tokens, fg), resolve(tokens, bg))).toBeGreaterThanOrEqual(4.5);
  });

  it.each(INDICATOR_PAIRS)("renders %s on %s at AA non-text contrast", (fg, bg) => {
    expect(wcagContrast(resolve(tokens, fg), resolve(tokens, bg))).toBeGreaterThanOrEqual(3);
  });
});
