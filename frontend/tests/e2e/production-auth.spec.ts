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

test("production entry keeps merchant wording and mobile navigation accessible", async ({ page }) => {
  test.skip(process.env.VITE_AUTH_MODE !== "production", "Run this focused check with VITE_AUTH_MODE=production.");

  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ actor: merchantAdmin, csrf_token: "synthetic-csrf-nonce" }) });
  });
  await page.route("**/api/v1/me", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(merchantAdmin) });
  });
  await page.route("**/api/v1/ops/summary", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ total_conversations: 0, active_conversations: 0, waiting_conversations: 0, resolved_conversations: 0, pending_refund_reviews: 0, recent_activity: [] }),
    });
  });
  await page.route("**/api/v1/knowledge/policies*", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ policies: [] }) });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?surface=overview");
  await page.getByLabel("Username").fill("merchant-admin");
  await page.getByLabel("Password").fill("password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Store connection not configured.", { exact: false })).toBeVisible();
  await expect(page.getByText("LOCAL SYNTHETIC DEMO", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Start Demo/ })).toHaveCount(0);
  await expect(page.locator(".ws-icon")).not.toContainText("SE");
  await expect(page.locator(".ws-icon svg")).toBeVisible();

  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("navigation", { name: "Application surfaces" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
