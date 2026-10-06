import { expect, test } from "@playwright/test";

// Settings → Platforms, taking back what was registered by mistake (issue 5),
// end to end. The Platform is created over the API under a name unique to the
// run, so every locator is unambiguous beside whatever else the development
// database holds — and the test removes everything it made.
test("a Platform is refused while it holds an Account, then both are removed", async ({
  page,
  request,
}) => {
  const name = `E2E Vault ${Date.now()}`;
  const registered = await request.post("/api/platforms", {
    data: { name, kind: "cold_storage" },
  });
  expect(registered.status()).toBe(201);
  const { id } = await registered.json();
  const added = await request.post(`/api/platforms/${id}/accounts`, { data: { name: "Savings" } });
  expect(added.status()).toBe(201);

  await page.goto("/settings/platforms");
  const row = page.getByRole("article", { name });

  // Always clickable: the server alone says whether removal is allowed, and
  // its reason appears at the row.
  await row.getByRole("button", { name: `Remove ${name}`, exact: true }).click();
  await row.getByRole("button", { name: `Remove ${name} for good` }).click();
  await expect(row.getByRole("alert")).toHaveText(
    "This Platform still holds the Account 'Savings' — remove it first.",
  );

  // Keep backs out of the two-step without removing anything.
  await row.getByRole("button", { name: "Remove Savings", exact: true }).click();
  await row.getByRole("button", { name: "Keep Savings" }).click();
  await expect(row.getByText("Savings", { exact: true })).toBeVisible();

  await row.getByRole("button", { name: "Remove Savings", exact: true }).click();
  await row.getByRole("button", { name: "Remove Savings for good" }).click();
  await expect(row.getByText("Savings", { exact: true })).toHaveCount(0);
  // The refusal named an Account that is gone now, so it does not linger.
  await expect(row.getByRole("alert")).toHaveCount(0);

  // The Platform's two-step is still open from the refusal.
  await row.getByRole("button", { name: `Remove ${name} for good` }).click();
  await expect(row).toHaveCount(0);
});

// Renaming a Platform (issue 13), end to end: the row's Edit action opens the
// name in place, a taken name is refused in the server's words at the row, a
// free one is saved and read back from the row. Two Platforms under names
// unique to the run, both removed again.
test("a Platform is refused a taken name, then renamed", async ({ page, request }) => {
  const stamp = Date.now();
  const taken = `E2E Taken ${stamp}`;
  const name = `E2E Typo ${stamp}`;
  const renamed = `E2E Corrected ${stamp}`;
  const ids: number[] = [];
  for (const platformName of [taken, name]) {
    const registered = await request.post("/api/platforms", {
      data: { name: platformName, kind: "cold_storage" },
    });
    expect(registered.status()).toBe(201);
    ids.push((await registered.json()).id);
  }

  await page.goto("/settings/platforms");
  const row = page.getByRole("article", { name, exact: true });

  // Cancel leaves everything as it was.
  await row.getByRole("button", { name: `Edit ${name}`, exact: true }).click();
  await expect(row.getByLabel("Name")).toHaveValue(name);
  await row.getByLabel("Name").fill("Never saved");
  await row.getByRole("button", { name: "Cancel" }).click();
  await expect(row.getByRole("heading", { name, exact: true })).toBeVisible();

  await row.getByRole("button", { name: `Edit ${name}`, exact: true }).click();
  await row.getByLabel("Name").fill(taken);
  await row.getByRole("button", { name: "Save" }).click();
  await expect(row.getByRole("alert")).toHaveText(`'${taken}' is already registered as this kind.`);

  // The form is still open on the refused name; a free one goes through.
  await row.getByLabel("Name").fill(renamed);
  await row.getByRole("button", { name: "Save" }).click();
  await expect(
    page.getByRole("article", { name: renamed, exact: true }).getByRole("heading", {
      name: renamed,
      exact: true,
    }),
  ).toBeVisible();
  await expect(row).toHaveCount(0);

  for (const id of ids) {
    expect((await request.delete(`/api/platforms/${id}`)).status()).toBe(204);
  }
});
