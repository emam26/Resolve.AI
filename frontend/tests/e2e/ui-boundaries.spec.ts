import { expect, test, type Page } from "@playwright/test";

const timestamp = "2026-01-01T00:00:00Z";

type ConversationState = "AI_ACTIVE" | "HANDOFF_QUEUED" | "HUMAN_ACTIVE" | "RESOLVED";
type RefundState = "PENDING_REVIEW" | "APPROVED_EXTERNAL_ACTION_REQUIRED" | "REJECTED";

function actorFor(demoActorId: string) {
  if (demoActorId === "support_001") {
    return {
      actor_id: "support_001",
      display_name: "Demo Support Agent",
      role: "support_agent",
      customer_id: null,
      permissions: ["support:read", "support:write"],
    };
  }
  if (demoActorId === "refund_approver_001") {
    return {
      actor_id: "refund_approver_001",
      display_name: "Demo Refund Approver",
      role: "refund_approver",
      customer_id: null,
      permissions: ["refund:read", "refund:decide"],
    };
  }
  return {
    actor_id: "customer_001",
    display_name: "Demo Customer",
    role: "customer",
    customer_id: "customer_001",
    permissions: ["customer:read", "customer:write"],
  };
}

function message(messageId: string, authorType: "customer" | "assistant" | "staff", content: string) {
  return {
    message_id: messageId,
    author_type: authorType,
    content,
    created_at: timestamp,
  };
}

async function installSyntheticApi(page: Page) {
  let conversationState: ConversationState = "HANDOFF_QUEUED";
  let messages = [message("msg-queued", "customer", "I need help with a delayed order.")];
  let refundState: RefundState = "PENDING_REVIEW";
  const refund = {
    refund_id: "refund_e2e",
    conversation_id: "conv_e2e",
    order_id: "order_1001",
    amount_cents: 2500,
    reason: "Delivery delay review",
    state: refundState,
    requested_by: "support_001",
    decided_by: null,
    decision_note: null,
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const body = request.postDataJSON() as Record<string, string> | null;
    const fulfill = async (payload: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });

    if (path === "/api/v1/auth/demo-login" && method === "POST") {
      const demoActorId = body?.demo_actor_id ?? "customer_001";
      await fulfill({ session_id: `${demoActorId}-session`, actor: actorFor(demoActorId) });
      return;
    }

    if (path === "/api/v1/orders/order_1001" && method === "GET") {
      await fulfill({
        order_id: "order_1001",
        status: "delayed",
        payment_status: "paid",
        shipment_status: "delayed",
        estimated_delivery_date: "2026-11-08",
      });
      return;
    }

    if (path === "/api/v1/conversations" && method === "POST") {
      conversationState = "AI_ACTIVE";
      messages = [];
      await fulfill({ conversation_id: "conv_e2e", channel: "widget", state: conversationState, order_id: "order_1001", messages });
      return;
    }

    if (path === "/api/v1/conversations/conv_e2e/messages" && method === "POST") {
      const content = body?.content ?? "";
      const customerMessage = message(`msg-customer-${messages.length}`, "customer", content);
      const isSupported = content.includes("delivery dates");
      const assistantMessage = message(
        `msg-assistant-${messages.length}`,
        "assistant",
        isSupported ? "Delivery dates are estimates under the published policy." : "I could not find sufficient published evidence for that question.",
      );
      messages = [...messages, customerMessage, assistantMessage];
      await fulfill({
        conversation_id: "conv_e2e",
        state: conversationState,
        message: customerMessage,
        assistant_reply: assistantMessage,
        evidence: isSupported ? [{
          document_id: "shipping-policy",
          document_version: "v1",
          section: "Delivery estimates",
          release_id: "release-1",
          visibility: "public",
          score: 0.91,
          text: "Delivery dates are estimates.",
        }] : [],
        handoff_reason: isSupported ? null : "No sufficient published customer policy evidence",
        retrieval_mode: "lexical",
        generation_mode: "deterministic",
        citation_ids: isSupported ? ["shipping-policy:v1:delivery"] : [],
      });
      return;
    }

    if (path === "/api/v1/conversations/conv_e2e/handoff" && method === "POST") {
      conversationState = "HANDOFF_QUEUED";
      await fulfill({ conversation_id: "conv_e2e", channel: "widget", state: conversationState, order_id: "order_1001", messages });
      return;
    }

    if (path === "/api/v1/support/inbox" && method === "GET") {
      await fulfill({ conversations: [{
        conversation_id: "conv_e2e",
        channel: "widget",
        state: conversationState,
        order_id: "order_1001",
        customer_id: "customer_001",
        assigned_staff_id: conversationState === "HUMAN_ACTIVE" ? "support_001" : null,
        messages,
      }] });
      return;
    }

    if (path === "/api/v1/support/conversations/conv_e2e/claim" && method === "POST") {
      conversationState = "HUMAN_ACTIVE";
      await fulfill({ conversation_id: "conv_e2e", channel: "widget", state: conversationState, order_id: "order_1001", customer_id: "customer_001", assigned_staff_id: "support_001", messages });
      return;
    }

    if (path === "/api/v1/support/conversations/conv_e2e/messages" && method === "POST") {
      const staffMessage = message(`msg-staff-${messages.length}`, "staff", body?.content ?? "");
      messages = [...messages, staffMessage];
      await fulfill({
        conversation_id: "conv_e2e",
        state: conversationState,
        message: staffMessage,
        assistant_reply: null,
        evidence: [],
        handoff_reason: null,
        retrieval_mode: "not_applicable",
        generation_mode: "deterministic",
        citation_ids: [],
      });
      return;
    }

    if (path === "/api/v1/support/conversations/conv_e2e/refunds" && method === "POST") {
      await fulfill({ ...refund, state: refundState });
      return;
    }

    if (path === "/api/v1/refunds" && method === "GET") {
      await fulfill({ refunds: [{ ...refund, state: refundState }] });
      return;
    }

    const refundDecision = path.match(/^\/api\/v1\/refunds\/refund_e2e\/(approve|reject)$/);
    if (refundDecision && method === "POST") {
      refundState = refundDecision[1] === "approve" ? "APPROVED_EXTERNAL_ACTION_REQUIRED" : "REJECTED";
      await fulfill({
        ...refund,
        state: refundState,
        decided_by: "refund_approver_001",
        decision_note: refundState === "REJECTED" ? "Synthetic review rejected." : "Approved for external action; no payment operation was performed.",
      });
      return;
    }

    if (path === "/api/v1/support/conversations/conv_e2e/resolve" && method === "POST") {
      conversationState = "RESOLVED";
      await fulfill({ conversation_id: "conv_e2e", channel: "widget", state: conversationState, order_id: "order_1001", customer_id: "customer_001", assigned_staff_id: "support_001", messages });
      return;
    }

    await fulfill({ error: { code: "not_found", message: `Unhandled synthetic route ${method} ${path}`, details: {} } }, 404);
  });
}

test("customer gets grounded citations and safely hands off unsupported questions", async ({ page }) => {
  await installSyntheticApi(page);
  await page.goto("/?surface=widget-preview");

  const widget = page.locator('section[aria-labelledby="widget-title"]');
  await expect(widget.getByRole("heading", { name: "ShopEase support", exact: true })).toBeVisible();
  await expect(widget.getByRole("button", { name: "Start Demo Customer session" })).toBeVisible();
  await widget.getByRole("button", { name: "Start Demo Customer session" }).click();

  await expect(widget.getByLabel("Order ID")).toBeVisible();
  await widget.getByLabel("Order ID").fill("order_1001");
  await widget.getByRole("button", { name: "Open widget conversation" }).click();
  await expect(widget.getByLabel("Your message")).toBeVisible();
  await expect(widget.getByRole("button", { name: "Send message" })).toBeDisabled();

  await widget.getByLabel("Your message").fill("Are delivery dates guaranteed?");
  await widget.getByRole("button", { name: "Send message" }).click();
  await expect(widget.getByText("Grounded answer", { exact: true })).toBeVisible();
  await expect(widget.getByText(/shipping-policy.*v1/)).toBeVisible();
  await expect(widget.getByText(/lexical.*deterministic/)).toBeVisible();

  await widget.getByLabel("Your message").fill("Where do I update my login email address?");
  await widget.getByRole("button", { name: "Send message" }).click();
  await expect(widget.getByText("Human review recommended", { exact: true })).toBeVisible();
  await expect(widget.getByText(/No sufficient published customer policy evidence/)).toBeVisible();

  await widget.getByRole("button", { name: "Request human support" }).click();
  await expect(widget.getByText("Human support requested", { exact: true })).toBeVisible();
  await expect(widget.getByRole("button", { name: "Request human support" })).toHaveCount(0);
  await expect(widget.getByLabel("Your message")).toBeDisabled();
});

test("customer can verify the owned order before opening a conversation", async ({ page }) => {
  await installSyntheticApi(page);
  await page.goto("/?surface=widget-preview");

  const widget = page.locator('section[aria-labelledby="widget-title"]');
  await widget.getByRole("button", { name: "Start Demo Customer session" }).click();
  await widget.getByLabel("Order ID").fill("order_1001");
  await widget.getByRole("button", { name: "Check order status" }).click();

  const lookup = widget.locator(".order-summary");
  await expect(lookup).toContainText("Authorized order lookup");
  await expect(lookup).toContainText("order_1001");
  await expect(lookup).toContainText("delayed");
  await expect(lookup).toContainText("2026-11-08");

  await widget.getByRole("button", { name: "Open widget conversation" }).click();
  await expect(widget.getByText(/Conversation conv_e2e/)).toBeVisible();
});

test("staff takeover, refund rejection, and resolution leave closed records read-only", async ({ page }) => {
  await installSyntheticApi(page);
  await page.goto("/?surface=widget-preview");

  const staff = page.locator('section[aria-labelledby="staff-title"]');
  const approval = page.locator('section[aria-labelledby="refund-title"]');
  await page.getByRole("navigation", {name:"Application surfaces"}).getByRole("button", {name:/^Conversations/}).click();
  await staff.getByRole("button", { name: "Start Demo Support session" }).click();
  await expect(staff.getByRole("button", { name: /conv_e2e/ })).toBeVisible();
  await expect(staff.getByRole("button", { name: "Approve for external action" })).toHaveCount(0);
  await staff.getByRole("button", { name: /conv_e2e/ }).click();
  await staff.getByRole("button", { name: "Claim conversation" }).click();
  await expect(staff.locator('section[aria-labelledby="staff-conversation-title"]').getByText("HUMAN_ACTIVE", { exact: true })).toBeVisible();

  await staff.getByRole("textbox", { name: "Staff reply" }).fill("A support agent is reviewing the synthetic order.");
  await staff.getByRole("button", { name: "Send staff reply" }).click();
  await expect(staff.locator(".staff-transcript").getByText("A support agent is reviewing the synthetic order.", { exact: true })).toBeVisible();

  const refundAmount = staff.getByLabel("Amount (USD)");
  await refundAmount.fill("51.00");
  await expect(refundAmount).toHaveAttribute("max", "50");
  expect(await refundAmount.evaluate((element) => !(element as HTMLInputElement).validity.valid)).toBe(true);
  await expect(staff.getByRole("alert")).toHaveCount(0);
  await staff.getByRole("button", { name: "Create review request" }).click();

  await refundAmount.fill("25.00");
  await staff.getByLabel("Reason").fill("Delivery delay review");
  await staff.getByRole("button", { name: "Create review request" }).click();
  await expect(staff.getByRole("status")).toContainText("refund_e2e is pending separate approver review");

  await page.getByRole("navigation", {name:"Application surfaces"}).getByRole("button", {name:/^Refund approvals/}).click();
  await approval.getByRole("button", { name: "Start Demo Approver session" }).click();
  await expect(approval.locator(".refund-card").getByText("refund_e2e", { exact: true })).toBeVisible();
  await approval.getByRole("button", { name: "Reject" }).click();
  await expect(approval.locator(".refund-card").getByText("REJECTED", { exact: true })).toBeVisible();
  await expect(approval.getByRole("button", { name: "Reject", exact: true })).toHaveCount(0);
  await expect(approval.getByRole("button", { name: "Approve for external action" })).toHaveCount(0);
  await expect(approval.getByText("This review is closed; no payment operation was performed.", { exact: true })).toBeVisible();

  await page.getByRole("navigation", {name:"Application surfaces"}).getByRole("button", {name:/^Conversations/}).click();
  await staff.getByRole("button", { name: "Resolve" }).click();
  await expect(staff.getByText("Conversation resolved", { exact: true })).toBeVisible();
  await expect(staff.getByRole("textbox", { name: "Staff reply" })).toHaveCount(0);
  await expect(staff.getByRole("button", { name: "Resolve", exact: true })).toHaveCount(0);
});

test("keeps loading controls labelled and reports a customer API network failure", async ({ page }) => {
  await page.route("**/api/v1/auth/demo-login", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 100));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "customer-session",
        actor: actorFor("customer_001"),
      }),
    });
  });
  await page.route("**/api/v1/conversations", async (route) => route.abort("failed"));
  await page.goto("/?surface=widget-preview");

  const widget = page.locator('section[aria-labelledby="widget-title"]');
  const startButton = widget.getByRole("button", { name: "Start Demo Customer session" });
  await startButton.click();
  await expect(widget.getByRole("button", { name: /Starting demo session/ })).toBeVisible();
  await expect(widget.getByLabel("Order ID")).toBeVisible();
  await widget.getByLabel("Order ID").fill("order_1001");
  await widget.getByRole("button", { name: "Open widget conversation" }).click();
  await expect(widget.getByRole("alert")).toContainText("The local API could not be reached.");
  await expect(widget.getByRole("button", { name: "Open widget conversation" })).toBeEnabled();
});
