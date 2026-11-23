import { expect, test, type Page } from "@playwright/test";

const adminActor = {
  actor_id: "merchant_admin_001",
  display_name: "Demo Merchant Admin",
  role: "merchant_admin",
  customer_id: null,
  permissions: ["workspace:admin"],
};

async function installWorkspaceApi(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const fulfill = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

    if (url.pathname === "/api/v1/auth/demo-login" && request.method() === "POST") {
      return fulfill({ session_id: "admin-session", actor: adminActor });
    }
    if (url.pathname === "/api/v1/ops/summary") {
      return fulfill({
        total_conversations: 4,
        active_conversations: 2,
        waiting_conversations: 1,
        resolved_conversations: 1,
        pending_refund_reviews: 1,
        recent_activity: [{
          conversation_id: "conv_1001",
          state: "HANDOFF_QUEUED",
          order_id: "order_1001",
          customer_id: "customer_001",
          assigned_staff_id: null,
          activity_type: "message",
          last_activity_at: "2026-11-23T10:00:00Z",
        }],
      });
    }
    if (url.pathname === "/api/v1/knowledge/policies" && request.method() === "GET") {
      return fulfill({ policies: [{
        document_id: "delivery-policy",
        document_version: "v2",
        section: "Delayed shipments",
        release_id: "release_2026_11_01",
        status: "published",
        visibility: "public",
        text: "Contact support for an updated estimate.",
      }] });
    }
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy") {
      return fulfill({
        document_id: "delivery-policy",
        policies: [{
          document_id: "delivery-policy",
          document_version: "v2",
          section: "Delayed shipments",
          release_id: "release_2026_11_01",
          status: "published",
          visibility: "public",
          text: "Contact support for an updated estimate.",
        }],
      });
    }
    if (url.pathname === "/api/v1/workspace/team") {
      return fulfill({ team: [adminActor] });
    }
    if (url.pathname === "/api/v1/workspace/settings") {
      return fulfill({
        merchant_name: "ResolveAI Demo Merchant",
        policy_source: "POLICY_CORPUS",
        policy_retrieval_mode: "lexical",
        response_generation_mode: "deterministic",
        database_ready: true,
        commerce_database_configured: false,
      });
    }
    return fulfill({ error: { code: "not_found", message: "Unhandled workspace route", details: {} } }, 404);
  });
}

test("workspace overview and knowledge catalog use authorized API data", async ({ page }) => {
  await installWorkspaceApi(page);
  await page.goto("/?surface=overview");
  await page.getByRole("button", { name: "Start Demo Workspace session" }).click();
  await expect(page.getByRole("heading", { name: /clear view of today/ })).toBeVisible();
  await expect(page.getByText("Total conversations").locator("..").getByText("4", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Knowledge" }).click();
  await expect(page.getByRole("heading", { name: "Published policy evidence, in context." })).toBeVisible();
  await expect(page.getByText("delivery-policy · v2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /delivery-policy.*v2/ }).click();
  await expect(page.getByRole("heading", { name: "delivery-policy" })).toBeVisible();
  await expect(page.getByText("Contact support for an updated estimate.", { exact: true })).toBeVisible();
});

test("widget-only mode does not expose staff surfaces", async ({ page }) => {
  await page.goto("/?surface=widget");
  await expect(page.getByRole("button", { name: "Start Demo Customer session" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Application surfaces" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Support inbox" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Refund review" })).toHaveCount(0);
});

test("workspace surfaces read from the local API", async ({ page }) => {
  await page.goto("/?surface=overview");
  await page.getByRole("button", { name: "Start Demo Workspace session" }).click();
  await expect(page.getByRole("heading", { name: /clear view of today/ })).toBeVisible();
  await expect(page.getByText("Total conversations").locator("..").getByText(/^\d+$/)).toBeVisible();
  await page.getByRole("button", { name: "Knowledge" }).click();
  await expect(page.getByText("delivery-policy · v2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /delivery-policy.*v2/ }).click();
  await expect(page.getByText("A delivery investigation may be opened", { exact: false })).toBeVisible();
});
