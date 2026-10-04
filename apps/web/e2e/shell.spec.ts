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
  await expect(page.locator("header").getByText("dev", { exact: true })).toBeVisible();
  await expect(page.locator("aside").getByText(/^[0-9a-f]{7,}$/)).toBeVisible();
});

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
