import { expect, type Page, test } from "@playwright/test";

const PASSWORD = "correct horse battery staple";
const NEW_PASSWORD = "a rather different passphrase";
// The one code the stand-in's authenticator shows.
const CODE = "287082";
const SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
const URI = `otpauth://totp/Open%20Leprechaun%3Aadmin?secret=${SECRET}&issuer=Open%20Leprechaun`;

/**
 * The e2e servers run in development, where nobody authenticates and there is
 * no Session to end. These journeys need one, so the browser is told it faces
 * a production instance: the auth endpoints are answered here, by a stand-in
 * that keeps the same promises the API's own tests hold the real one to.
 * Everything else still reaches the real API.
 */
async function standInForProduction(
  page: Page,
  { sessions = 2, twoFactor = false }: { sessions?: number; twoFactor?: boolean } = {},
) {
  const instance = { loggedIn: true, sessions, twoFactor, enrolling: false };
  const wrongCode = {
    status: 403,
    json: { detail: "Wrong code, or one already used. Wait for the next code and try again." },
  };

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
    const body = route.request().postDataJSON() as { code?: string };
    if (instance.twoFactor && body.code === undefined) {
      return route.fulfill({
        status: 401,
        json: { detail: "Enter the code from your authenticator app.", result: "code_required" },
      });
    }
    if (instance.twoFactor && body.code !== CODE) {
      return route.fulfill({ status: 401, json: { detail: wrongCode.json.detail, result: "wrong_code" } });
    }
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
    const body = route.request().postDataJSON() as { current_password: string; code?: string };
    if (body.current_password !== PASSWORD) {
      return route.fulfill({ status: 403, json: { detail: "Wrong current password." } });
    }
    if (instance.twoFactor && body.code !== CODE) {
      return route.fulfill(wrongCode);
    }
    instance.sessions = 1;
    return route.fulfill({ status: 204 });
  });
  await page.route("**/api/auth/two-factor", (route) =>
    route.fulfill({ json: { enabled: instance.twoFactor } }),
  );
  await page.route("**/api/auth/two-factor/enrollment", (route) => {
    instance.enrolling = true;
    return route.fulfill({ status: 201, json: { secret: SECRET, uri: URI } });
  });
  await page.route("**/api/auth/two-factor/activation", (route) => {
    const body = route.request().postDataJSON() as { code: string };
    if (!instance.enrolling || body.code !== CODE) {
      return route.fulfill(wrongCode);
    }
    instance.enrolling = false;
    instance.twoFactor = true;
    instance.sessions = 1;
    return route.fulfill({ status: 204 });
  });
  await page.route("**/api/auth/two-factor/disable", (route) => {
    const body = route.request().postDataJSON() as { current_password: string; code: string };
    if (body.current_password !== PASSWORD) {
      return route.fulfill({ status: 403, json: { detail: "Wrong current password." } });
    }
    if (body.code !== CODE) {
      return route.fulfill(wrongCode);
    }
    instance.twoFactor = false;
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

  await page.getByRole("complementary").getByRole("button", { name: "Sign out" }).click();

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

  await page.getByRole("complementary").getByRole("button", { name: "Sign out" }).click();

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

  await page.getByRole("complementary").getByRole("button", { name: "Sign out" }).click();
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

  // The Security page and its password fields can still be on screen here.
  await page.getByRole("textbox", { name: "Password", exact: true }).fill(PASSWORD);
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

test("production reminds on every page while two-factor is off, and development never does", async ({
  page,
}) => {
  await page.goto("/holdings");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Two-factor reminder" })).toHaveCount(0);

  await standInForProduction(page);
  await page.goto("/holdings");
  const reminder = page.getByRole("complementary", { name: "Two-factor reminder" });
  await expect(reminder).toContainText("Two-factor is off.");

  // It stays put on the next page, and leads to where it is fixed.
  await page.goto("/transactions");
  await reminder.getByRole("link", { name: "Set it up" }).click();
  await expect(page).toHaveURL(/\/settings\/security$/);
});

test("setting two-factor up shows the QR code, URI and secret, and waits for a verifying code", async ({
  page,
}) => {
  const instance = await standInForProduction(page, { sessions: 3 });
  await page.goto("/settings/security");
  const twoFactor = page.getByRole("region", { name: "Two-factor" });
  await expect(twoFactor.getByTestId("two-factor-state")).toHaveText("Off");

  await twoFactor.getByRole("button", { name: "Set up two-factor" }).click();

  await expect(twoFactor.getByRole("img", { name: "QR code of the two-factor setup URI" })).toBeVisible();
  await expect(twoFactor.getByTestId("two-factor-uri")).toHaveText(URI);
  await expect(twoFactor.getByTestId("two-factor-secret")).toHaveText(
    "JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP",
  );
  // Said before anything activates: no recovery codes, and the way back in.
  await expect(twoFactor.getByText("There are no recovery codes.")).toBeVisible();
  await expect(twoFactor.getByText("pnpm auth:disable-two-factor")).toBeVisible();
  await expect(twoFactor.getByText("docs/runbook.md")).toBeVisible();

  await twoFactor.getByLabel("Authenticator code").fill("000000");
  await twoFactor.getByRole("button", { name: "Verify and turn on" }).click();
  await expect(twoFactor.getByRole("alert")).toContainText("Wrong code");
  expect(instance.twoFactor).toBe(false);

  await twoFactor.getByLabel("Authenticator code").fill(CODE);
  await twoFactor.getByRole("button", { name: "Verify and turn on" }).click();

  await expect(twoFactor.getByTestId("two-factor-state")).toHaveText("On");
  await expect(twoFactor.getByRole("status")).toContainText("Two-factor is on");
  // The secret is gone from the page, the reminder from the shell, and the
  // Sessions the password alone had opened from the count.
  await expect(twoFactor.getByTestId("two-factor-secret")).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "Two-factor reminder" })).toHaveCount(0);
  await expect(page.getByTestId("session-count")).toHaveText("1");
});

test("login asks for the code once the password is right", async ({ page }) => {
  const instance = await standInForProduction(page, { twoFactor: true });
  instance.loggedIn = false;
  await page.goto("/login");

  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();

  // Asked for, not reported as a failure.
  await expect(page.getByRole("heading", { name: "Enter the code" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(instance.loggedIn).toBe(false);

  await page.getByLabel("Authenticator code").fill("000000");
  await page.getByRole("button", { name: "Verify and log in" }).click();
  await expect(page.getByRole("alert")).toContainText("Wrong code");

  await page.getByLabel("Authenticator code").fill(CODE);
  await page.getByRole("button", { name: "Verify and log in" }).click();

  await expect(page).toHaveURL(/\/$/);
  expect(instance.loggedIn).toBe(true);
});

test("with two-factor on, changing the password and turning it off both take a code", async ({
  page,
}) => {
  const instance = await standInForProduction(page, { twoFactor: true });
  await page.goto("/settings/security");
  const password = page.getByRole("region", { name: "Password" });

  await password.getByLabel("Current password").fill(PASSWORD);
  await password.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
  await password.getByLabel("Confirm new password").fill(NEW_PASSWORD);
  await password.getByLabel("Authenticator code").fill(CODE);
  await password.getByRole("button", { name: "Change password" }).click();
  await expect(password.getByRole("status")).toContainText("Password changed");

  const twoFactor = page.getByRole("region", { name: "Two-factor" });
  await twoFactor.getByLabel("Current password").fill(PASSWORD);
  await twoFactor.getByLabel("Authenticator code").fill(CODE);
  await twoFactor.getByRole("button", { name: "Turn off two-factor" }).click();

  await expect(twoFactor.getByTestId("two-factor-state")).toHaveText("Off");
  expect(instance.twoFactor).toBe(false);
  await expect(page.getByRole("complementary", { name: "Two-factor reminder" })).toBeVisible();
});
