import { expect, test } from "@playwright/test";

// The shell's accessibility claims, asserted where they can actually break:
// in a real browser with a real keyboard.

test("keyboard users get a skip link first, and it lands on the content region", async ({
  page,
}) => {
  await page.goto("/");
  // The auth gate mounts the shell only after the instance answers who it is;
  // a Tab pressed into the not-yet-mounted shell would focus nothing.
  const skipLink = page.getByRole("link", { name: "Skip to content" });
  await expect(skipLink).toBeAttached();

  await page.keyboard.press("Tab");
  await expect(skipLink).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(page.locator("#content")).toBeFocused();
});

test("the navigation names itself and marks the current page", async ({ page }) => {
  await page.goto("/");

  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link", { name: "Health" })).toHaveAttribute("aria-current", "page");
});

test("a development instance wears its badge and shows the checked-out commit", async ({
  page,
}) => {
  await page.goto("/");

  // The e2e servers run in development, so the badge must be present and the
  // version line must carry a short git hash rather than a release version.
  const sidebar = page.getByRole("complementary");
  await expect(sidebar.getByText("dev", { exact: true })).toBeVisible();
  await expect(sidebar.getByText(/^[0-9a-f]{7,}$/)).toBeVisible();
});

// The frame (docs/agents/design.md, "Layout and width"), asserted on the real
// boxes: a class name would not notice a sidebar that had started to scroll.

test("a desktop window has no top bar, and the theme is chosen from the sidebar", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");

  await expect(page.getByRole("banner")).toBeHidden();
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeHidden();

  await page.getByRole("complementary").getByRole("button", { name: "Theme" }).click();
  await page.getByRole("menuitemcheckbox", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("at 1440×900 the sidebar shows every entry without scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link").last()).toBeInViewport({ ratio: 1 });
  const overflow = await nav.evaluate((node) => node.scrollHeight - node.clientHeight);
  expect(overflow).toBe(0);
});

test("the sheet fills the window up to its cap, and shows the canvas beyond it", async ({
  page,
}) => {
  const sheet = page.locator("#content").locator("xpath=../..");
  const margins = async () => {
    const box = await sheet.boundingBox();
    const viewport = page.viewportSize();
    if (!box || !viewport) {
      throw new Error("The sheet has no box.");
    }
    return { left: box.x, right: viewport.width - box.x - box.width };
  };

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.locator("#content")).toBeVisible();
  expect(await margins()).toEqual({ left: 0, right: 0 });

  await page.setViewportSize({ width: 1920, height: 1080 });
  const wide = await margins();
  expect(wide.left).toBeGreaterThan(0);
  expect(wide.right).toBe(wide.left);
});

test("a phone keeps the top bar, and the navigation opens from it", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const bar = page.getByRole("banner");
  await expect(bar).toBeVisible();
  await expect(bar.getByRole("button", { name: "Theme" })).toBeVisible();
  await expect(page.getByRole("complementary")).toBeHidden();

  await bar.getByRole("button", { name: "Open navigation" }).click();
  const nav = page.getByRole("dialog").getByRole("navigation", { name: "Primary" });
  await nav.getByRole("link", { name: "Holdings" }).click();
  await expect(page).toHaveURL(/\/holdings$/);
  await expect(page.getByRole("dialog")).toBeHidden();
});

for (const width of [390, 1024, 1440, 1920]) {
  test(`the page never scrolls sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/futures");
    await expect(page.getByRole("heading", { level: 1, name: "Futures" })).toBeVisible();

    const overflow = await page
      .locator("html")
      .evaluate((node) => node.scrollWidth - node.clientWidth);
    expect(overflow).toBe(0);
  });
}

test("the theme toggle switches the theme and the choice survives a reload", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  await expect(page.locator("html")).not.toHaveClass(/dark/);

  await page.getByRole("button", { name: "Theme" }).click();
  await page.getByRole("menuitemcheckbox", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);

  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("the browser chrome is tinted for the chosen theme, not the system's", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  const themeColor = page.locator('meta[name="theme-color"]');
  const light = await themeColor.getAttribute("content");
  expect(light).toBeTruthy();

  await page.getByRole("button", { name: "Theme" }).click();
  await page.getByRole("menuitemcheckbox", { name: "Dark" }).click();
  await expect(themeColor).not.toHaveAttribute("content", light ?? "");
  const dark = await themeColor.getAttribute("content");
  expect(dark).toBeTruthy();

  await page.reload();
  await expect(themeColor).toHaveAttribute("content", dark ?? "");
});

// A path the server does not know is answered with the application, so a
// missing icon would still be a 200 — only the content type tells them apart.
for (const [path, type] of [
  ["/favicon.svg", "image/svg+xml"],
  ["/favicon.ico", "image/x-icon"],
  ["/apple-touch-icon.png", "image/png"],
] as const) {
  test(`${path} is served as an image`, async ({ page, request }) => {
    await page.goto("/");
    await expect(page.locator(`link[href="${path}"]`)).toBeAttached();

    const response = await request.get(path);
    expect(response.headers()["content-type"]).toContain(type);
  });
}
