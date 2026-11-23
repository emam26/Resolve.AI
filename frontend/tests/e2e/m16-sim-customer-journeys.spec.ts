import { expect, test, type Page, type Request } from "@playwright/test";

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
  return { message_id: messageId, author_type: authorType, content, created_at: timestamp };
}

function requestBody(request: Request): Record<string, unknown> {
  try {
    return (request.postDataJSON() as Record<string, unknown> | null) ?? {};
  } catch {
    return {};
  }
}

function sessionId(request: Request): string | null {
  return request.headers().authorization?.replace(/^Bearer\s+/i, "") ?? null;
}

type JourneyOptions = {
  failCustomerLoginOnce?: boolean;
  failCustomerMessageOnce?: boolean;
  failRefundOnce?: boolean;
};

async function installJourneyApi(page: Page, options: JourneyOptions = {}) {
  let conversationState: ConversationState = "HANDOFF_QUEUED";
  let messages = [message("msg-start", "customer", "I need help with my synthetic order.")];
  let refundState: RefundState = "PENDING_REVIEW";
  let customerLoginAttempts = 0;
  let customerMessageAttempts = 0;
  let refundAttempts = 0;
  const refundRequestKeys: string[] = [];
  const refund = {
    refund_id: "refund_sim_001",
    conversation_id: "conv_sim_001",
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
    const body = requestBody(request);
    const actorSession = sessionId(request);
    const fulfill = (payload: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
    const deny = () => fulfill({ error: { code: "forbidden", message: "This demo role is not authorized for that action.", details: {} } }, 403);

    if (path === "/api/v1/auth/demo-login" && method === "POST") {
      const demoActorId = String(body.demo_actor_id ?? "customer_001");
      if (demoActorId === "customer_001" && options.failCustomerLoginOnce && customerLoginAttempts++ === 0) {
        return fulfill({ error: { code: "service_unavailable", message: "Synthetic API unavailable.", details: {} } }, 503);
      }
      return fulfill({ session_id: `${demoActorId}-session`, actor: actorFor(demoActorId) });
    }

    if (path === "/api/v1/conversations" && method === "POST") {
      if (actorSession !== "customer_001-session") return deny();
      conversationState = "AI_ACTIVE";
      messages = [];
      return fulfill({ conversation_id: "conv_sim_001", channel: "widget", state: conversationState, order_id: "order_1001", messages });
    }

    if (path === "/api/v1/conversations/conv_sim_001/messages" && method === "POST") {
      if (actorSession !== "customer_001-session") return deny();
      if (options.failCustomerMessageOnce && customerMessageAttempts++ === 0) return route.abort("failed");

      const content = String(body.content ?? "");
      const isSupported = content.includes("delivery dates");
      const customerMessage = message(`msg-customer-${messages.length}`, "customer", content);
      const assistantMessage = isSupported
        ? message(
            `msg-assistant-${messages.length}`,
            "assistant",
            "Delivery dates are estimates under the published shipping policy.",
          )
        : null;
      messages = [...messages, customerMessage, ...(assistantMessage ? [assistantMessage] : [])];
      return fulfill({
        conversation_id: "conv_sim_001",
        state: conversationState,
        message: customerMessage,
        assistant_reply: assistantMessage,
        evidence: isSupported ? [{
          document_id: "shipping-policy",
          document_version: "v2",
          section: "Delivery estimates",
          release_id: "release-2026-01",
          visibility: "public",
          score: 0.91,
          text: "Delivery dates are estimates.",
        }] : [],
        handoff_reason: isSupported ? null : "No sufficient published customer policy evidence",
        retrieval_mode: "semantic",
        generation_mode: "deterministic",
        citation_ids: isSupported ? ["shipping-policy:v2:delivery-estimates"] : [],
      });
    }

    if (path === "/api/v1/conversations/conv_sim_001/handoff" && method === "POST") {
      if (actorSession !== "customer_001-session") return deny();
      conversationState = "HANDOFF_QUEUED";
      return fulfill({ conversation_id: "conv_sim_001", channel: "widget", state: conversationState, order_id: "order_1001", messages });
    }

    if (path === "/api/v1/support/inbox" && method === "GET") {
      if (actorSession !== "support_001-session") return deny();
      return fulfill({ conversations: [{
        conversation_id: "conv_sim_001",
        channel: "widget",
        state: conversationState,
        order_id: "order_1001",
        customer_id: "customer_001",
        assigned_staff_id: conversationState === "HUMAN_ACTIVE" ? "support_001" : null,
        messages,
      }] });
    }

    if (path === "/api/v1/support/conversations/conv_sim_001/claim" && method === "POST") {
      if (actorSession !== "support_001-session") return deny();
      conversationState = "HUMAN_ACTIVE";
      return fulfill({ conversation_id: "conv_sim_001", channel: "widget", state: conversationState, order_id: "order_1001", customer_id: "customer_001", assigned_staff_id: "support_001", messages });
    }

    if (path === "/api/v1/support/conversations/conv_sim_001/messages" && method === "POST") {
      if (actorSession !== "support_001-session" || conversationState !== "HUMAN_ACTIVE") return deny();
      const staffMessage = message(`msg-staff-${messages.length}`, "staff", String(body.content ?? ""));
      messages = [...messages, staffMessage];
      return fulfill({ conversation_id: "conv_sim_001", state: conversationState, message: staffMessage, assistant_reply: null, evidence: [], handoff_reason: null, retrieval_mode: "not_applicable", generation_mode: "deterministic", citation_ids: [] });
    }

    if (path === "/api/v1/support/conversations/conv_sim_001/refunds" && method === "POST") {
      if (actorSession !== "support_001-session" || conversationState !== "HUMAN_ACTIVE") return deny();
      const idempotencyKey = String(body.idempotency_key ?? "");
      refundAttempts += 1;
      refundRequestKeys.push(idempotencyKey);
      if (options.failRefundOnce && refundAttempts === 1) {
        return fulfill({ error: { code: "temporary_failure", message: "Synthetic refund service unavailable.", details: {} } }, 503);
      }
      if (!refundRequestKeys.slice(0, -1).includes(idempotencyKey)) refundState = "PENDING_REVIEW";
      return fulfill({ ...refund, state: refundState });
    }

    if (path === "/api/v1/refunds" && method === "GET") {
      if (actorSession !== "refund_approver_001-session") return deny();
      return fulfill({ refunds: [{ ...refund, state: refundState }] });
    }

    const refundDecision = path.match(/^\/api\/v1\/refunds\/refund_sim_001\/(approve|reject)$/);
    if (refundDecision && method === "POST") {
      if (actorSession !== "refund_approver_001-session") return deny();
      if (refundState !== "PENDING_REVIEW") {
        return fulfill({ error: { code: "conflict", message: "This refund review is already closed.", details: {} } }, 409);
      }
      refundState = refundDecision[1] === "approve" ? "APPROVED_EXTERNAL_ACTION_REQUIRED" : "REJECTED";
      return fulfill({
        ...refund,
        state: refundState,
        decided_by: "refund_approver_001",
        decision_note: "Approved for external action; no payment operation was performed.",
      });
    }

    if (path === "/api/v1/support/conversations/conv_sim_001/resolve" && method === "POST") {
      if (actorSession !== "support_001-session" || conversationState !== "HUMAN_ACTIVE") return deny();
      conversationState = "RESOLVED";
      return fulfill({ conversation_id: "conv_sim_001", channel: "widget", state: conversationState, order_id: "order_1001", customer_id: "customer_001", assigned_staff_id: "support_001", messages });
    }

    return fulfill({ error: { code: "not_found", message: `Unhandled synthetic route ${method} ${path}`, details: {} } }, 404);
  });

  return { refundRequestKeys };
}

test("customer can correct a question, see grounded evidence, and hand off an unsupported turn", async ({ page }) => {
  await installJourneyApi(page);
  await page.goto("/?surface=widget");

  const widget = page.locator('section[aria-labelledby="widget-title"]');
  await widget.getByRole("button", { name: "Start Demo Customer session" }).click();
  await widget.getByLabel("Order ID").fill("order_1001");
  await widget.getByRole("button", { name: "Open widget conversation" }).click();

  const messageBox = widget.getByLabel("Your message");
  await messageBox.fill("Which carrier is handling this?");
  await widget.getByRole("button", { name: "Send message" }).click();
  await expect(widget.locator(".resolution-panel")).toContainText("Human review recommended");
  await expect(widget.locator(".resolution-panel")).toContainText("No sufficient published customer policy evidence");

  await messageBox.fill("Are delivery dates guaranteed?");
  await widget.getByRole("button", { name: "Send message" }).click();
  const grounded = widget.locator(".resolution-panel");
  await expect(grounded).toContainText("Grounded answer");
  await expect(grounded).toContainText("semantic");
  await expect(grounded).toContainText("deterministic");
  await expect(grounded).toContainText("shipping-policy · v2");
  await expect(grounded).toContainText("Delivery estimates · release-2026-01");
  await expect(widget.locator(".conversation-meta .state-badge")).toContainText("AI_ACTIVE");

  await messageBox.fill("Where do I update my login email address?");
  await widget.getByRole("button", { name: "Send message" }).click();
  await expect(widget.locator(".resolution-panel")).toContainText("Human review recommended");
  await widget.getByRole("button", { name: "Request human support" }).click();
  await expect(widget.locator(".m1-state")).toContainText("Human support requested");
  await expect(messageBox).toBeDisabled();
  await expect(widget.getByRole("button", { name: "Request human support" })).toHaveCount(0);
});

test("customer-only, staff, and approver journeys keep role surfaces separated", async ({ page }) => {
  await installJourneyApi(page);
  await page.goto("/?surface=widget");
  await expect(page.getByRole("button", { name: "Start Demo Customer session" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Application surfaces" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Support inbox" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Refund review" })).toHaveCount(0);

  await page.goto("/");
  const staff = page.locator('section[aria-labelledby="staff-title"]');
  const approval = page.locator('section[aria-labelledby="refund-title"]');
  await staff.getByRole("button", { name: "Start Demo Support session" }).click();
  await expect(staff).toContainText("support_001 · support_agent");
  await expect(staff.getByRole("button", { name: "Approve for external action" })).toHaveCount(0);

  await approval.getByRole("button", { name: "Start Demo Approver session" }).click();
  await expect(approval).toContainText("refund_approver_001 · refund_approver");
  await expect(approval.getByText("APPROVED_EXTERNAL_ACTION_REQUIRED", { exact: true })).toHaveCount(0);
  await expect(staff.getByRole("button", { name: "Approve for external action" })).toHaveCount(0);
});

test("a failed refund request can retry with the same idempotency key and close once", async ({ page }) => {
  const api = await installJourneyApi(page, { failRefundOnce: true });
  await page.goto("/");

  const staff = page.locator('section[aria-labelledby="staff-title"]');
  const approval = page.locator('section[aria-labelledby="refund-title"]');
  await staff.getByRole("button", { name: "Start Demo Support session" }).click();
  await staff.getByRole("button", { name: /conv_sim_001/ }).click();
  await staff.getByRole("button", { name: "Claim conversation" }).click();
  await staff.getByLabel("Amount (USD)").fill("25.00");
  await staff.getByLabel("Reason").fill("Delivery delay review");
  await staff.getByRole("button", { name: "Create review request" }).click();
  await expect(staff.getByRole("alert")).toContainText("Synthetic refund service unavailable.");

  await staff.getByRole("button", { name: "Create review request" }).click();
  await expect(staff.getByRole("status")).toContainText("refund_sim_001 is pending separate approver review");
  expect(api.refundRequestKeys).toHaveLength(2);
  expect(api.refundRequestKeys[0]).toBe(api.refundRequestKeys[1]);

  await approval.getByRole("button", { name: "Start Demo Approver session" }).click();
  await expect(approval.getByText("refund_sim_001", { exact: true })).toBeVisible();
  await approval.getByRole("button", { name: "Approve for external action" }).click();
  const refundCard = approval.locator(".refund-card").filter({ hasText: "refund_sim_001" });
  await expect(refundCard).toContainText("APPROVED_EXTERNAL_ACTION_REQUIRED");
  await expect(refundCard).toContainText("no payment operation was performed");
  await expect(refundCard.getByRole("button", { name: "Approve for external action" })).toHaveCount(0);
});

test("login and message failures recover without losing the customer draft", async ({ page }) => {
  await installJourneyApi(page, { failCustomerLoginOnce: true, failCustomerMessageOnce: true });
  await page.goto("/?surface=widget");
  const widget = page.locator('section[aria-labelledby="widget-title"]');
  const startButton = widget.getByRole("button", { name: "Start Demo Customer session" });

  await startButton.click();
  await expect(widget.getByRole("alert")).toContainText("Synthetic API unavailable.");
  await expect(startButton).toBeEnabled();
  await startButton.click();
  await widget.getByLabel("Order ID").fill("order_1001");
  await widget.getByRole("button", { name: "Open widget conversation" }).click();

  const messageBox = widget.getByLabel("Your message");
  const question = "Are delivery dates guaranteed?";
  await messageBox.fill(question);
  await widget.getByRole("button", { name: "Send message" }).click();
  await expect(widget.getByRole("alert")).toContainText("The local API could not be reached.");
  await expect(messageBox).toHaveValue(question);
  await expect(widget.getByRole("button", { name: "Send message" })).toBeEnabled();

  await widget.getByRole("button", { name: "Send message" }).click();
  await expect(widget.locator(".resolution-panel")).toContainText("Grounded answer");
  await expect(widget.locator(".resolution-panel")).toContainText("shipping-policy · v2");
});
