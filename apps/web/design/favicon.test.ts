import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { formatHex } from "culori";
import { describe, expect, it } from "vitest";
import { resolve, themeTokens } from "./tokens";

// Browser chrome cannot read a CSS variable, so the favicon and the theme-color
// meta state their colours as literals — the one place a colour lives outside
// index.css. Held to the tokens here, so tuning one fails loudly rather than
// leaving a stale tab icon.

const read = (path: string) =>
  readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8");

const hex = (selector: string, token: string) =>
  formatHex(resolve(themeTokens(selector), token));

describe("the favicon", () => {
  const svg = read("../public/favicon.svg");

  it("sets its tile in the ink theme's background", () => {
    expect(svg.match(/<rect[^>]*fill="([^"]+)"/)?.[1]).toBe(hex(".dark", "--background"));
  });

  it("draws its clover in the ink theme's primary", () => {
    expect(svg.match(/stroke="([^"]+)"/)?.[1]).toBe(hex(".dark", "--primary"));
  });
});

describe("the theme-color meta", () => {
  const meta = read("../index.html").match(/<meta\s+name="theme-color"[^>]*>/)?.[0] ?? "";

  it.each([
    ["light", ":root"],
    ["dark", ".dark"],
  ])("offers the %s theme its background", (theme, selector) => {
    expect(meta.match(new RegExp(`data-${theme}="([^"]+)"`))?.[1]).toBe(
      hex(selector, "--background"),
    );
  });

  it("starts as the light theme's, for a page whose script never ran", () => {
    expect(meta.match(/\scontent="([^"]+)"/)?.[1]).toBe(hex(":root", "--background"));
  });
});
