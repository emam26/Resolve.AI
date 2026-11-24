import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

test("capture the running synthetic owner walkthrough surfaces", async ({ page }) => {
  await page.goto("/?surface=widget");
  await expect(page.getByRole("heading", { name: "ShopEase support", exact: true })).toBeVisible();
  await page.screenshot({ path: "../docs/uat/screenshots/customer-widget.png", fullPage: true });

  await page.goto("/?surface=overview");
  await page.getByRole("button", { name: "Start Demo Workspace session" }).click();
  await expect(page.getByRole("heading", { name: /clear view of today/ })).toBeVisible();
  await page.screenshot({ path: "../docs/uat/screenshots/workspace-overview.png", fullPage: true });

  await page.getByRole("button", { name: "Knowledge" }).click();
  await expect(page.getByRole("heading", { name: "Maintain policy evidence safely." })).toBeVisible();
  await page.screenshot({ path: "../docs/uat/screenshots/knowledge-management.png", fullPage: true });

  await page.goto("/?surface=support");
  await page.getByRole("button", { name: "Start Demo Support session" }).click();
  await expect(page.getByRole("heading", { name: "Support inbox" })).toBeVisible();
  await page.screenshot({ path: "../docs/uat/screenshots/support-inbox.png", fullPage: true });
});
