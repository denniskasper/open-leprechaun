import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// The shell answers to the window, page content to its column
// (docs/agents/design.md, "Layout and width"). A viewport breakpoint inside a
// page measures a window the sidebar has already taken 240px of, so pages and
// the patterns they are built from use container queries (`@md:`) only.

const ROOTS = ["src/pages", "src/components/patterns"];

/** `sm:`, `max-lg:`, `min-[40rem]:` and kin — but not `@md:` or `@max-lg:`. */
const VIEWPORT_VARIANT =
  /(?<![\w@[-])(?:(?:max-)?(?:sm|md|lg|xl|2xl)|(?:min|max)-\[[^\]]+\]):(?=\S)/g;

/** Each component source under a root, as its name there and its path. */
function sources(root: string): [string, string][] {
  const directory = fileURLToPath(new URL(`../${root}/`, import.meta.url));
  return readdirSync(directory, { recursive: true, encoding: "utf8" })
    .filter((name) => name.endsWith(".tsx"))
    .map((name) => [name, join(directory, name)]);
}

describe("the viewport-variant pattern", () => {
  it.each(["sm:grid-cols-2", "max-md:hidden", "lg:grid-cols-3", "min-[40rem]:flex"])(
    "catches %s",
    (variant) => {
      expect(`className="grid ${variant}"`.match(VIEWPORT_VARIANT)).not.toBeNull();
    },
  );

  it.each(["@md:grid-cols-2", "@max-md:hidden", "@[30rem]:flex", '{ sm: "size-2.5" }'])(
    "lets %s pass",
    (text) => {
      expect(text.match(VIEWPORT_VARIANT)).toBeNull();
    },
  );
});

describe.each(ROOTS)("%s", (root) => {
  it.each(sources(root))("%s uses no viewport breakpoint", (_name, path) => {
    expect(readFileSync(path, "utf8").match(VIEWPORT_VARIANT) ?? []).toEqual([]);
  });
});
