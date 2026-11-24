import { expect, test } from "@playwright/test";

const merchantAdmin = {
  actor_id: "merchant_admin_001",
  display_name: "Demo Merchant Admin",
  role: "merchant_admin",
  customer_id: null,
  permissions: ["workspace:read", "policy:write"],
};

test("expired provisioned sessions return to the sign-in screen", async ({ page }) => {
  test.skip(process.env.VITE_AUTH_MODE !== "production", "Run this focused check with VITE_AUTH_MODE=production.");

  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ actor: merchantAdmin, csrf_token: "synthetic-csrf-nonce" }),
    });
  });
  await page.route("**/api/v1/me", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(merchantAdmin) });
  });
  await page.route("**/api/v1/ops/summary", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "session_expired", message: "Session expired.", details: {} } }),
    });
  });

  await page.goto("/?surface=overview");
  await page.getByLabel("Username").fill("synthetic-admin");
  await page.getByLabel("Password").fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("session expired");
});

test("lost CSRF state returns to the sign-in screen", async ({ page }) => {
  test.skip(process.env.VITE_AUTH_MODE !== "production", "Run this focused check with VITE_AUTH_MODE=production.");

  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ actor: merchantAdmin, csrf_token: "synthetic-csrf-nonce" }),
    });
  });
  await page.route("**/api/v1/me", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(merchantAdmin) });
  });
  await page.route("**/api/v1/ops/summary", async (route) => {
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "csrf_required", message: "CSRF token is missing or invalid.", details: {} } }),
    });
  });

  await page.goto("/?surface=overview");
  await page.getByLabel("Username").fill("synthetic-admin");
  await page.getByLabel("Password").fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("session expired");
});
