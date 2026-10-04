import { wcagContrast } from "culori";
import { describe, expect, it } from "vitest";
import { resolve, themeTokens } from "./tokens";

// The ticket's claim, held as a test: both themes meet WCAG AA.

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
