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
