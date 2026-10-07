import { expect, type Page, test } from "@playwright/test";

// The measures (docs/agents/design.md, "Layout and width"), held on the real
// boxes at the width where a missing one shows: on a large monitor the column
// is far wider than any form, sentence or row list should run.

const REM = 16;
const FORM = 45 * REM;
const LIST = 60 * REM;

const SCREENS = [
  "/",
  "/first-run",
  "/holdings",
  "/portfolio",
  "/inbox",
  "/transactions",
  "/futures",
  "/transfers",
  "/imports",
  "/instruments",
  "/corporate-actions",
  "/export",
  "/tax/overview",
  "/settings/platforms",
  "/settings/connections",
  "/settings/statutory",
  "/settings/scheduled-tasks",
  "/settings/security",
];

/** A form that only opens on a button: the screen, then the button. */
const OPENED = [
  ["/settings/platforms", "Register Platform"],
  ["/transactions", "Record Transaction"],
  ["/instruments", "Add security"],
  ["/instruments", "Add coin or currency"],
] as const;

// A table is the column's width by right, and the page header's actions sit
// at the end of its rule.
const OUTSIDE_TABLES = ":not(table *):not(header *)";

async function widest(page: Page, selector: string): Promise<number> {
  const widths = await page
    .locator("#content")
    .locator(selector)
    .evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().width));
  return Math.max(0, ...widths);
}

/** The longest line of running text, measured on the text rather than its box. */
async function longestLine(page: Page): Promise<number> {
  const widths = await page
    .locator("#content")
    .locator(`p${OUTSIDE_TABLES}`)
    .evaluateAll((nodes) =>
      nodes.map((node) => {
        const range = node.ownerDocument.createRange();
        range.selectNodeContents(node);
        return range.getBoundingClientRect().width;
      }),
    );
  return Math.max(0, ...widths);
}

async function expectMeasured(page: Page) {
  expect(await widest(page, `:is(input, select, textarea)${OUTSIDE_TABLES}`)).toBeLessThanOrEqual(
    FORM,
  );
  expect(await widest(page, `:is(ul, ol)${OUTSIDE_TABLES}`)).toBeLessThanOrEqual(LIST);
  expect(await longestLine(page)).toBeLessThanOrEqual(LIST);
}

test.use({ viewport: { width: 1920, height: 1080 } });

for (const screen of SCREENS) {
  test(`${screen} keeps its fields, lists and sentences within a measure`, async ({ page }) => {
    await page.goto(screen);
    await expect(page.locator("#content").getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");

    await expectMeasured(page);
  });
}

for (const [screen, button] of OPENED) {
  test(`${screen}: the form behind "${button}" keeps to a measure`, async ({ page }) => {
    await page.goto(screen);
    await page.locator("#content").getByRole("button", { name: button }).first().click();
    await expect(page.locator("#content").locator("form").first()).toBeVisible();

    await expectMeasured(page);
  });
}
