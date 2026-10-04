import { expect, type Page, test } from "@playwright/test";

const PASSWORD = "correct horse battery staple";
const NEW_PASSWORD = "a rather different passphrase";

/**
 * The e2e servers run in development, where nobody authenticates and there is
 * no Session to end. These journeys need one, so the browser is told it faces
 * a production instance: the auth endpoints are answered here, by a stand-in
 * that keeps the same promises the API's own tests hold the real one to.
 * Everything else still reaches the real API.
 */
async function standInForProduction(page: Page, { sessions = 2 }: { sessions?: number } = {}) {
  const instance = { loggedIn: true, sessions };

  await page.route("**/api/meta", (route) =>
    route.fulfill({ json: { environment: "production", version: "0.0.0-e2e" } }),
  );
  await page.route("**/api/auth/setup", (route) => route.fulfill({ json: { required: false } }));
  await page.route("**/api/auth/session", (route) =>
    instance.loggedIn
      ? route.fulfill({ json: { subject: "admin" } })
      : route.fulfill({ status: 401, json: { detail: "Authentication required." } }),
  );
  await page.route("**/api/auth/login", (route) => {
    instance.loggedIn = true;
    instance.sessions += 1;
    return route.fulfill({ json: { token: "e2e", expires_at: "2099-01-01T00:00:00Z" } });
  });
  await page.route("**/api/auth/logout", (route) => {
    instance.loggedIn = false;
    instance.sessions -= 1;
    return route.fulfill({ status: 204 });
  });
  await page.route("**/api/auth/sessions", (route) => {
    if (route.request().method() === "DELETE") {
      instance.loggedIn = false;
      instance.sessions = 0;
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ json: { active: instance.sessions } });
  });
  await page.route("**/api/auth/password", (route) => {
    const body = route.request().postDataJSON() as { current_password: string };
    if (body.current_password !== PASSWORD) {
      return route.fulfill({ status: 403, json: { detail: "Wrong current password." } });
    }
    instance.sessions = 1;
    return route.fulfill({ status: 204 });
  });

  return instance;
}

test("a bare /settings opens the first panel rather than an index", async ({ page }) => {
  await page.goto("/settings");

  await expect(page).toHaveURL(/\/settings\/platforms$/);
  await expect(page.getByRole("heading", { level: 1, name: "Platforms" })).toBeVisible();
});

test("a development instance says there is nothing to secure and offers no way out", async ({
  page,
}) => {
  await page.goto("/settings/security");

  await expect(page.getByRole("heading", { level: 1, name: "Security" })).toBeVisible();
  await expect(page.getByText("Nothing to secure in development")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
});

test("the header signs out of this session from any page", async ({ page }) => {
  await standInForProduction(page);
  await page.goto("/holdings");

  await page.getByRole("banner").getByRole("button", { name: "Sign out" }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
  // The session is gone for real: the shell sends a returning visitor back.
  await page.goto("/holdings");
  await expect(page).toHaveURL(/\/login$/);
});

test("the header's sign out is within reach on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await standInForProduction(page);
  await page.goto("/transactions");

  await page.getByRole("banner").getByRole("button", { name: "Sign out" }).click();

  await expect(page).toHaveURL(/\/login$/);
});

test("the Security panel counts the open sessions and signs out of all of them", async ({
  page,
}) => {
  const instance = await standInForProduction(page, { sessions: 3 });
  await page.goto("/settings/security");

  const sessions = page.getByRole("region", { name: "Sessions" });
  await expect(sessions.getByTestId("session-count")).toHaveText("3");
  await expect(sessions.getByText("2 others are open elsewhere")).toBeVisible();

  await sessions.getByRole("button", { name: "Sign out everywhere" }).click();

  await expect(page).toHaveURL(/\/login$/);
  expect(instance.sessions).toBe(0);
});

test("nothing read under the old session is shown under the next one", async ({ page }) => {
  const instance = await standInForProduction(page, { sessions: 3 });
  await page.goto("/settings/security");
  const count = page.getByTestId("session-count");
  await expect(count).toHaveText("3");

  await page.getByRole("banner").getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  // Hold the next session's answer back: a cache that survived the sign-out
  // would paint the old figure while this one is still on its way.
  instance.sessions = 7;
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/auth/sessions", async (route) => {
    await held;
    await route.fulfill({ json: { active: 8 } });
  });

  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Security" }).click();

  await expect(page.getByRole("region", { name: "Sessions" })).toBeVisible();
  await expect(count).toHaveCount(0);
  release();
  await expect(count).toHaveText("8");
});

test("changing the password demands the current one and reports what it revoked", async ({
  page,
}) => {
  await standInForProduction(page, { sessions: 3 });
  await page.goto("/settings/security");
  const password = page.getByRole("region", { name: "Password" });

  await password.getByLabel("Current password").fill("not the password");
  await password.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
  await password.getByLabel("Confirm new password").fill(NEW_PASSWORD);
  await password.getByRole("button", { name: "Change password" }).click();
  await expect(password.getByRole("alert")).toContainText("Wrong current password.");

  await password.getByLabel("Current password").fill(PASSWORD);
  await password.getByRole("button", { name: "Change password" }).click();

  await expect(password.getByRole("status")).toContainText("Password changed");
  // Still inside the shell, and the count now shows only this browser.
  await expect(page).toHaveURL(/\/settings\/security$/);
  await expect(page.getByTestId("session-count")).toHaveText("1");
});

test("a new password that differs from its confirmation never leaves the browser", async ({
  page,
}) => {
  await standInForProduction(page);
  let asked = false;
  await page.route("**/api/auth/password", (route) => {
    asked = true;
    return route.fulfill({ status: 204 });
  });
  await page.goto("/settings/security");
  const password = page.getByRole("region", { name: "Password" });

  await password.getByLabel("Current password").fill(PASSWORD);
  await password.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
  await password.getByLabel("Confirm new password").fill("something else entirely");
  await password.getByRole("button", { name: "Change password" }).click();

  await expect(password.getByRole("alert")).toHaveText("The two entries differ.");
  expect(asked).toBe(false);
});
