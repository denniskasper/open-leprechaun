import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Page content answers to its column, not the window (docs/agents/design.md,
// "Layout and width"). A 768px window is where the two part most: the sidebar
// is in, so the column is a phone's width while the window is a tablet's. Every
// grid on these screens has to have collapsed to what that column holds —
// nothing sticking out of its cell, no cell over another.

async function arrangeCash(request: APIRequestContext): Promise<void> {
  const platform = await request.post("/api/platforms", {
    data: { name: `E2E Columns ${Date.now()}`, kind: "bank" },
  });
  const platformId = ((await platform.json()) as { id: number }).id;
  const account = await request.post(`/api/platforms/${platformId}/accounts`, {
    data: { name: "Cash" },
  });
  const accountId = ((await account.json()) as { id: number }).id;
  const instruments = (await (await request.get("/api/instruments")).json()) as {
    id: number;
    is_numeraire: boolean;
  }[];
  await request.post("/api/transactions", {
    data: {
      type: "opening_balance",
      occurred_at: "2031-01-05T12:00:00Z",
      note: "e2e columns",
      reconstructed: "basis",
      estimated_basis_eur: "1250.00",
      legs: [
        {
          account_id: accountId,
          instrument_id: instruments.find((entry) => entry.is_numeraire)!.id,
          role: "in",
          quantity: "1250.00",
        },
      ],
    },
  });
  await request.post("/api/scheduled-tasks/portfolio_snapshot/run");
}

type Screen = {
  name: string;
  path: string;
  arrange?: (request: APIRequestContext) => Promise<unknown>;
  /** What to open once loaded, so its grids are in view. */
  open?: (page: Page) => Promise<unknown>;
};

const SCREENS: Screen[] = [
  { name: "Portfolio", path: "/portfolio", arrange: arrangeCash },
  { name: "Health", path: "/" },
  ...["Import a file", "Map a file", "Read an address"].map((button) => ({
    name: `Imports, ${button}`,
    path: "/imports",
    open: (page: Page) => page.getByRole("button", { name: button }).click(),
  })),
  {
    name: "Platforms",
    path: "/settings/platforms",
    open: (page) => page.getByRole("button", { name: "Register Platform" }).click(),
  },
  {
    name: "Connections",
    path: "/settings/connections",
    open: (page) => page.getByRole("button", { name: "Add Connection" }).click(),
  },
  { name: "Statutory", path: "/settings/statutory" },
  { name: "Scheduled tasks", path: "/settings/scheduled-tasks" },
  { name: "Security", path: "/settings/security" },
];

type Misfit = { grid: string; problem: string };

/**
 * Every grid in the content region outside a table, judged on its laid-out
 * boxes: a cell that overlaps another, or a box inside a cell that runs past
 * the cell's edges. A table's frame scrolls by design, so what it holds is
 * left out, as is anything visually hidden and anything placed out of the
 * flow on purpose — a lamp's halo breathes past its dot.
 */
function misfits(page: Page): Promise<Misfit[]> {
  return page.locator("#content").evaluate((content) => {
    // Node-side types know no DOM, so the shapes are taken from the region.
    type Box = ReturnType<typeof content.getBoundingClientRect>;
    type Node = NonNullable<typeof content.firstElementChild>;
    const document = content.ownerDocument;
    const style = (node: Node) => document.defaultView!.getComputedStyle(node);
    const name = (node: Node) =>
      `${node.tagName.toLowerCase()}.${[...node.classList].join(".")}`.slice(0, 120);
    const shown = (node: Node) => {
      const box = node.getBoundingClientRect();
      return box.width > 1 && box.height > 1 && !node.closest(".sr-only, .table-frame");
    };
    /** The box each line of text inside a node takes, with the text. */
    const lines = (node: Node) =>
      [...node.childNodes]
        .filter((child) => child.nodeType === child.TEXT_NODE && child.textContent?.trim())
        .map((child) => {
          const range = document.createRange();
          range.selectNodeContents(child);
          return { box: range.getBoundingClientRect(), text: child.textContent!.trim() };
        });

    const found: Misfit[] = [];
    const grids = [...content.querySelectorAll("*")].filter(
      (node) => style(node).display.endsWith("grid") && shown(node),
    );
    for (const grid of grids) {
      const cells = [...grid.children].filter(shown);
      const boxes = cells.map((cell) => cell.getBoundingClientRect());
      boxes.forEach((a, i) =>
        boxes.slice(i + 1).forEach((b, j) => {
          const across = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const down = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (across > 1 && down > 1) {
            found.push({
              grid: name(grid),
              problem: `${name(cells[i]!)} overlaps ${name(cells[i + 1 + j]!)}`,
            });
          }
        }),
      );
      cells.forEach((cell, i) => {
        const outside = (box: Box) =>
          box.width > 0 && (box.left < boxes[i]!.left - 1 || box.right > boxes[i]!.right + 1);
        const inside = [cell, ...cell.querySelectorAll("*")].filter(
          (node) => shown(node) && style(node).position !== "absolute",
        );
        const runaway =
          inside
            .filter((node) => node !== cell && outside(node.getBoundingClientRect()))
            .map(name)[0] ??
          inside
            .flatMap(lines)
            .filter((line) => outside(line.box))
            .map((line) => `"${line.text.slice(0, 40)}"`)[0];
        if (runaway) {
          found.push({ grid: name(grid), problem: `${runaway} runs out of ${name(cell)}` });
        }
      });
    }
    return found;
  });
}

test.use({ viewport: { width: 768, height: 1024 } });

for (const screen of SCREENS) {
  test(`${screen.name} fits its grids to the column at 768px`, async ({ page, request }) => {
    await screen.arrange?.(request);
    await page.goto(screen.path);
    await expect(page.locator("#content").getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await screen.open?.(page);

    expect(await misfits(page)).toEqual([]);
    expect(await page.locator("html").evaluate((html) => html.scrollWidth - html.clientWidth)).toBe(
      0,
    );
  });
}
