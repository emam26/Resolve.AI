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
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy/versions") {
      return fulfill({ versions: [] });
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
  await expect(page.getByRole("heading", { name: /Welcome,/ })).toBeVisible();
  await expect(page.getByText("Total conversations: 4", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Knowledge base" }).click();
  await expect(page.getByRole("heading", { name: "Knowledge base" })).toBeVisible();
  await expect(page.getByText("delivery-policy · v2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /delivery-policy.*v2/ }).click();
  await expect(page.getByRole("heading", { name: "delivery-policy" })).toBeVisible();
  await expect(page.getByText("Contact support for an updated estimate.", { exact: true })).toBeVisible();
});

test("widget-only mode does not expose staff surfaces", async ({ page }) => {
  await page.goto("/?surface=widget");
  await expect(page.getByRole("button", { name: "Start Demo Customer session" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Application surfaces" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Conversations" })).toHaveCount(0);
  await expect(page.locator('section[aria-labelledby="refund-title"]')).toHaveCount(0);
});

test("workspace surfaces read from the local API", async ({ page }) => {
  await page.goto("/?surface=overview");
  await page.getByRole("button", { name: "Start Demo Workspace session" }).click();
  await expect(page.getByRole("heading", { name: /Welcome,/ })).toBeVisible();
  await expect(page.getByText(/^Total conversations: \d+$/)).toBeVisible();
  await page.getByRole("button", { name: "Knowledge base" }).click();
  await expect(page.getByText("delivery-policy · v2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /delivery-policy.*v2/ }).click();
  await expect(page.getByText("A delivery investigation may be opened", { exact: false })).toBeVisible();
});

test("actual policy API enforces admin lifecycle and fails closed without an index updater", async ({ request }) => {
  const supportLogin = await request.post("/api/v1/auth/demo-login", {
    data: { demo_actor_id: "support_001" },
  });
  const adminLogin = await request.post("/api/v1/auth/demo-login", {
    data: { demo_actor_id: "merchant_admin_001" },
  });
  expect(supportLogin.ok()).toBeTruthy();
  expect(adminLogin.ok()).toBeTruthy();
  const supportHeaders = { Authorization: `Bearer ${(await supportLogin.json()).session_id}` };
  const adminHeaders = { Authorization: `Bearer ${(await adminLogin.json()).session_id}` };
  const documentId = `playwright-policy-${Date.now()}`;
  const denied = await request.post("/api/v1/knowledge/policies", {
    headers: supportHeaders,
    data: {
      document_id: documentId,
      title: "Playwright policy",
      visibility: "public",
      sections: [{ section: "Window", text: "Thirty days." }],
    },
  });
  expect(denied.status()).toBe(403);
  const created = await request.post("/api/v1/knowledge/policies", {
    headers: adminHeaders,
    data: {
      document_id: documentId,
      title: "Playwright policy",
      visibility: "public",
      sections: [{ section: "Window", text: "Thirty days." }],
    },
  });
  expect(created.status()).toBe(201);
  const version = await created.json();
  const validation = await request.post(`/api/v1/knowledge/policies/${version.version_id}/validate`, { headers: adminHeaders });
  expect((await validation.json()).valid).toBeTruthy();
  const indexed = await request.post(`/api/v1/knowledge/policies/${version.version_id}/index`, { headers: adminHeaders });
  expect(indexed.status()).toBe(200);
  expect((await indexed.json()).state).toBe("FAILED");
  const publish = await request.post(`/api/v1/knowledge/policies/${version.version_id}/publish`, { headers: adminHeaders });
  expect(publish.status()).toBe(409);
  const audit = await request.get(`/api/v1/knowledge/policies/${version.version_id}/audit`, { headers: adminHeaders });
  expect(audit.ok()).toBeTruthy();
  expect((await audit.json()).events.every((event: { revision?: number | null }) => typeof event.revision === "number")).toBeTruthy();
});

function policyMutationResponse(status: string, revision: number) {
  return {
    version_id: "delivery-policy-v3",
    document_id: "delivery-policy",
    title: "delivery-policy",
    document_version: "v3",
    release_id: "release_2026_11_23",
    status,
    visibility: "public",
    revision,
    sections: [{ section: "Delayed shipments", text: "Contact support for a current estimate." }],
    index_state: status === "published" ? "ready" : "draft",
  };
}

async function installPolicyManagementApi(page: Page, options: { conflict?: boolean } = {}) {
  let currentStatus = "draft";
  let currentRevision = 2;
  let lastRequest: { method: string; path: string; body: Record<string, unknown> } | null = null;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const fulfill = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    const body = request.postDataJSON?.() ?? {};
    if (url.pathname === "/api/v1/auth/demo-login" && request.method() === "POST") return fulfill({ session_id: "admin-session", actor: adminActor });
    if (url.pathname === "/api/v1/knowledge/policies" && request.method() === "GET") {
      return fulfill({ policies: [
        { document_id: "delivery-policy", document_version: "v2", version_id: "delivery-policy-v2", title: "delivery-policy", section: "Delayed shipments", release_id: "release_2026_11_01", status: "published", visibility: "public", text: "Contact support for an earlier estimate.", revision: 4, is_active: true },
        { document_id: "delivery-policy", document_version: "v3", version_id: "delivery-policy-v3", title: "delivery-policy", section: "Delayed shipments", release_id: "release_2026_11_23", status: currentStatus, visibility: "public", text: "Contact support for a current estimate.", revision: currentRevision, is_active: currentStatus === "published" },
      ] });
    }
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy" && request.method() === "GET") {
      return fulfill({ document_id: "delivery-policy", policies: [{ document_id: "delivery-policy", document_version: "v3", version_id: "delivery-policy-v3", title: "delivery-policy", section: "Delayed shipments", release_id: "release_2026_11_23", status: currentStatus, visibility: "public", text: "Contact support for a current estimate.", revision: currentRevision, is_active: currentStatus === "published" }] });
    }
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy/versions" && request.method() === "GET") {
      return fulfill({ versions: [
        { ...policyMutationResponse("published", 4), version_id: "delivery-policy-v2", document_version: "v2", release_id: "release_2026_11_01", status: "published", sections: [{ section: "Delayed shipments", text: "Contact support for an earlier estimate." }] },
        policyMutationResponse(currentStatus, currentRevision),
      ] });
    }
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy-v3" && request.method() === "PATCH") {
      lastRequest = { method: request.method(), path: url.pathname, body };
      if (options.conflict) return fulfill({ error: { code: "revision_conflict", message: "The policy changed in another session.", details: { current_revision: 3 } } }, 409);
      currentRevision = 3;
      return fulfill(policyMutationResponse(currentStatus, currentRevision));
    }
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy-v3/validate" && request.method() === "POST") {
      return fulfill({ valid: true, errors: [], state: currentStatus.toUpperCase(), revision: currentRevision });
    }
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy-v3/index" && request.method() === "POST") {
      currentStatus = "testable";
      currentRevision = 3;
      return fulfill(policyMutationResponse(currentStatus, currentRevision));
    }
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy-v3/publish" && request.method() === "POST") {
      lastRequest = { method: request.method(), path: url.pathname, body };
      currentStatus = "published";
      currentRevision = 4;
      return fulfill(policyMutationResponse(currentStatus, currentRevision));
    }
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy/rollback" && request.method() === "POST") {
      lastRequest = { method: request.method(), path: url.pathname, body };
      currentStatus = "published";
      currentRevision = 5;
      return fulfill(policyMutationResponse(currentStatus, currentRevision));
    }
    if (url.pathname === "/api/v1/knowledge/policies/delivery-policy-v3/audit" && request.method() === "GET") {
      return fulfill({ events: [{ event_id: "audit-1", action: "publish", actor_id: "merchant_admin_001", from_status: "draft", to_status: "published", revision: 4, created_at: "2026-11-23T12:00:00Z" }] });
    }
    if (url.pathname === "/api/v1/ops/summary") return fulfill({ total_conversations: 0, active_conversations: 0, waiting_conversations: 0, resolved_conversations: 0, pending_refund_reviews: 0, recent_activity: [] });
    return fulfill({ error: { code: "not_found", message: "Unhandled policy test route", details: {} } }, 404);
  });
  return { getLastRequest: () => lastRequest };
}

test("admin can edit, publish, roll back, and inspect policy audit events", async ({ page }) => {
  const api = await installPolicyManagementApi(page);
  await page.goto("/?surface=knowledge");
  await page.getByRole("button", { name: "Start Demo Workspace session" }).click();
  await page.getByRole("button", { name: /delivery-policy.*v3/ }).click();
  await expect(page.getByRole("heading", { name: "Edit draft content" })).toBeVisible();
  await page.getByLabel("Content").fill("Contact support for a current estimate and delivery investigation.");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect.poll(() => api.getLastRequest()?.body.expected_revision).toBe(2);
  await expect(page.getByRole("button", { name: "Publish version" })).toBeVisible();
  await page.getByRole("button", { name: "Publish version" }).click();
  await expect(page.getByText("published", { exact: true }).last()).toBeVisible();
  await page.getByRole("button", { name: "Validate" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Validation passed" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Refresh index" }).click();
  await page.getByRole("button", { name: "View audit" }).click();
  await expect(page.getByText("publish", { exact: true })).toBeVisible();
  await page.getByLabel("Rollback target").selectOption("v2");
  await page.getByRole("button", { name: "Rollback" }).click();
  await expect.poll(() => api.getLastRequest()?.body).toMatchObject({ target_version: "v2", expected_revision: 3 });
});

test("stale policy edits show a structured conflict and widget stays customer-only", async ({ page }) => {
  await page.goto("/?surface=widget");
  await expect(page.getByRole("navigation", { name: "Application surfaces" })).toHaveCount(0);
  await expect(page.getByText("Create draft", { exact: true })).toHaveCount(0);

  const managementPage = await page.context().newPage();
  await installPolicyManagementApi(managementPage, { conflict: true });
  await managementPage.goto("/?surface=knowledge");
  await managementPage.getByRole("button", { name: "Start Demo Workspace session" }).click();
  await managementPage.getByRole("button", { name: /delivery-policy.*v3/ }).click();
  await managementPage.getByLabel("Content").fill("A concurrent edit should be preserved.");
  await managementPage.getByRole("button", { name: "Save changes" }).click();
  await expect(managementPage.getByRole("alert")).toContainText("Conflict");
  await expect(managementPage.getByRole("alert")).toContainText("revision_conflict");
});
