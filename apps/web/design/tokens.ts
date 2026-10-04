import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// The tokens live in CSS, so a check over them reads them from CSS — a colour
// tuned later is re-judged, not trusted.

const css = readFileSync(fileURLToPath(new URL("../src/index.css", import.meta.url)), "utf8");

export function themeTokens(selector: string): Map<string, string> {
  const block = css.match(new RegExp(`${selector.replace(".", "\\.")}\\s*\\{([^}]*)\\}`))?.[1];
  if (!block) throw new Error(`No ${selector} block found in index.css`);

  const tokens = new Map<string, string>();
  for (const [, name, value] of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    if (name !== undefined && value !== undefined) tokens.set(name, value.trim());
  }
  return tokens;
}

export function resolve(tokens: Map<string, string>, name: string): string {
  const value = tokens.get(name);
  if (!value) throw new Error(`Token ${name} is not defined`);
  const reference = value.match(/^var\((--[\w-]+)\)$/);
  return reference?.[1] !== undefined ? resolve(tokens, reference[1]) : value;
}
