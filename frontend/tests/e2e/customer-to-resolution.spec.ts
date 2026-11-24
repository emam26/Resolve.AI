import { expect, test } from "@playwright/test";

test("customer-to-resolution workflow preserves human and refund boundaries", async ({ page }) => {
  await page.goto("/");

  const widget = page.locator('section[aria-labelledby="widget-title"]');
  const staff = page.locator('section[aria-labelledby="staff-title"]');
  const approval = page.locator('section[aria-labelledby="refund-title"]');

  await expect(widget.getByRole("heading", { name: "ShopEase support", exact: true })).toBeVisible();
  await expect(widget.getByText("Demo only.", { exact: false })).toBeVisible();
  await widget.getByRole("button", { name: /Start Demo Customer session/ }).click();
  await widget.locator("#order-id").fill("order_1001");
  await widget.getByRole("button", { name: /Open widget conversation/ }).click();

  const conversationId = (await widget.locator(".conversation-meta").first().innerText()).match(/conv_\d+/)?.[0];
  expect(conversationId).toBeTruthy();

  const customerMessage = widget.locator("#message");
  await customerMessage.fill("Are delivery dates guaranteed?");
  await widget.getByRole("button", { name: "Send message" }).click();
  await expect(widget.getByText("Grounded answer", { exact: true })).toBeVisible();
  await expect(widget.getByText(/shipping-policy.*v1/)).toBeVisible();
  await expect(widget.getByText(/lexical.*deterministic/)).toBeVisible();

  await customerMessage.fill("Where do I update my login email address?");
  await widget.getByRole("button", { name: "Send message" }).click();
  await expect(widget.getByText("Human review recommended", { exact: true })).toBeVisible();
  await expect(widget.getByText(/No sufficient published customer policy evidence/)).toBeVisible();

  await widget.getByRole("button", { name: "Request human support" }).click();
  await expect(widget.getByText("Human support requested", { exact: true })).toBeVisible();

  await staff.getByRole("button", { name: /Start Demo Support session/ }).click();
  await expect(staff.getByRole("button", { name: new RegExp(conversationId as string) })).toBeVisible();
  await staff.getByRole("button", { name: new RegExp(conversationId as string) }).click();
  await staff.getByRole("button", { name: "Claim conversation" }).click();
  await expect(staff.locator('section[aria-labelledby="staff-conversation-title"]').getByText("HUMAN_ACTIVE", { exact: true })).toBeVisible();

  await staff.locator("#staff-message").fill("A support agent is reviewing the synthetic order.");
  await staff.getByRole("button", { name: "Send staff reply" }).click();
  await expect(staff.locator(".staff-transcript").getByText("A support agent is reviewing the synthetic order.", { exact: true })).toBeVisible();

  await staff.locator("#support-refund-amount").fill("25.00");
  await staff.getByRole("button", { name: "Create review request" }).click();
  const refundNotice = staff.getByText(/refund_[a-f0-9]+ is pending separate approver review/);
  await expect(refundNotice).toBeVisible();
  const refundId = (await refundNotice.innerText()).match(/refund_[a-f0-9]+/)?.[0];
  expect(refundId).toBeTruthy();

  await approval.getByRole("button", { name: /Start Demo Approver session/ }).click();
  await expect(approval.getByText(refundId as string, { exact: true })).toBeVisible();
  await approval.getByRole("button", { name: "Approve for external action" }).click();
  const refundCard = approval.locator(".refund-card").filter({ hasText: refundId as string });
  await expect(refundCard.getByText("APPROVED_EXTERNAL_ACTION_REQUIRED", { exact: true })).toBeVisible();
  await expect(refundCard.getByText(/no payment operation was performed/, { exact: false })).toBeVisible();

  await staff.getByRole("button", { name: "Resolve" }).click();
  await expect(staff.getByText("Conversation resolved", { exact: true })).toBeVisible();
  await expect(staff.locator("#staff-message")).toHaveCount(0);
});

test("customer login shows a safe API failure and keeps controls labeled", async ({ page }) => {
  await page.route("**/api/v1/auth/demo-login", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "service_unavailable", message: "Synthetic API unavailable.", details: {} },
      }),
    });
  });
  await page.goto("/");

  const widget = page.locator('section[aria-labelledby="widget-title"]');
  await expect(widget.locator("#order-id")).toHaveCount(0);
  await widget.getByRole("button", { name: /Start Demo Customer session/ }).click();
  await expect(widget.getByRole("alert")).toContainText("Synthetic API unavailable.");
  await expect(widget.getByRole("button", { name: /Start Demo Customer session/ })).toBeEnabled();
});

test("customer logout revokes the server session without persistent browser storage", async ({ page, request }) => {
  let logoutAuthorization = "";
  await page.route("**/api/v1/auth/logout", async (route) => {
    logoutAuthorization = route.request().headers().authorization ?? "";
    await route.continue();
  });

  await page.goto("/");
  const widget = page.locator('section[aria-labelledby="widget-title"]');
  await widget.getByRole("button", { name: /Start Demo Customer session/ }).click();
  await expect(widget.getByRole("button", { name: "End session" })).toBeVisible();

  await widget.getByRole("button", { name: "End session" }).click();
  await expect(widget.getByRole("button", { name: /Start Demo Customer session/ })).toBeVisible();
  await expect(widget.locator("#order-id")).toHaveCount(0);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  expect(logoutAuthorization).toMatch(/^Bearer\s+\S+$/);

  const protectedResponse = await request.get("/api/v1/orders/order_1001", {
    headers: { Authorization: logoutAuthorization },
  });
  expect(protectedResponse.status()).toBe(401);
});
