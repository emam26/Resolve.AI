"""Bounded synthetic ResolveAI load, stress, and soak profiles for Locust.

This file targets only a locally running ResolveAI API.  It uses the fixed
synthetic demo identities and never contacts a real commerce, payment, model,
or external customer service.  Select a profile with
``RESOLVEAI_LOCUST_PROFILE=load|stress|soak``.
"""

from __future__ import annotations

import os

from locust import HttpUser, LoadTestShape, between, task


PROFILE_STAGES = {
    "load": ((60, 8, 2), (120, 12, 2)),
    "stress": ((30, 20, 10), (90, 40, 10)),
    "soak": ((60, 8, 2), (600, 8, 1)),
}


class LocalVerificationShape(LoadTestShape):
    """Select a small deterministic profile rather than an open-ended run."""

    def tick(self):
        profile = os.getenv("RESOLVEAI_LOCUST_PROFILE", "load").casefold()
        stages = PROFILE_STAGES.get(profile)
        if stages is None:
            raise ValueError(
                "RESOLVEAI_LOCUST_PROFILE must be one of: load, stress, soak"
            )
        elapsed = self.get_run_time()
        max_seconds = os.getenv("RESOLVEAI_LOCUST_MAX_SECONDS")
        if max_seconds is not None and elapsed >= float(max_seconds):
            return None
        for duration, users, spawn_rate in stages:
            if elapsed < duration:
                return users, spawn_rate
        return None


class SyntheticCustomerUser(HttpUser):
    """Exercise authenticated customer reads and a grounded policy inquiry."""

    wait_time = between(0.1, 0.5)

    def on_start(self):
        response = self.client.post(
            "/api/v1/auth/demo-login",
            json={"demo_actor_id": "customer_001"},
            name="POST /api/v1/auth/demo-login",
        )
        if response.ok:
            self.authorization = {
                "Authorization": f"Bearer {response.json()['session_id']}"
            }
        else:
            self.authorization = {}

    @task(4)
    def authenticated_order_lookup(self):
        self.client.get(
            "/api/v1/orders/order_1001",
            headers=self.authorization,
            name="GET /api/v1/orders/{order_id} authorized",
        )

    @task(2)
    def policy_investigation(self):
        conversation = self.client.post(
            "/api/v1/conversations",
            headers=self.authorization,
            json={"channel": "widget", "order_id": "order_1001"},
            name="POST /api/v1/conversations",
        )
        if not conversation.ok:
            return
        conversation_id = conversation.json()["conversation_id"]
        self.client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.authorization,
            json={"content": "Are delivery dates guaranteed?"},
            name="POST /api/v1/conversations/{id}/messages policy",
        )


class SyntheticSupportUser(HttpUser):
    """Exercise support queue reads without mutating customer ownership."""

    wait_time = between(0.1, 0.5)

    def on_start(self):
        response = self.client.post(
            "/api/v1/auth/demo-login",
            json={"demo_actor_id": "support_001"},
            name="POST /api/v1/auth/demo-login support",
        )
        self.authorization = (
            {"Authorization": f"Bearer {response.json()['session_id']}"}
            if response.ok
            else {}
        )

    @task
    def support_inbox(self):
        self.client.get(
            "/api/v1/support/inbox",
            headers=self.authorization,
            name="GET /api/v1/support/inbox",
        )


class SyntheticRefundWorkflowUser(HttpUser):
    """Exercise one complete synthetic handoff-to-refund-review workflow."""

    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.customer_headers = self._login("customer_001", "customer")
        self.support_headers = self._login("support_001", "support")
        self.approver_headers = self._login("refund_approver_001", "approver")
        self.conversation_id = None
        self.refund_id = None
        self.refund_decided = False
        self.workflow_ready = False

        conversation = self.client.post(
            "/api/v1/conversations",
            headers=self.customer_headers,
            json={"channel": "widget", "order_id": "order_1001"},
            name="POST /api/v1/conversations workflow",
        )
        if not conversation.ok:
            return
        self.conversation_id = conversation.json()["conversation_id"]
        handoff = self.client.post(
            f"/api/v1/conversations/{self.conversation_id}/handoff",
            headers=self.customer_headers,
            name="POST /api/v1/conversations/{id}/handoff workflow",
        )
        if not handoff.ok:
            return
        inbox = self.client.get(
            "/api/v1/support/inbox",
            headers=self.support_headers,
            name="GET /api/v1/support/inbox workflow",
        )
        if not inbox.ok:
            return
        claim = self.client.post(
            f"/api/v1/support/conversations/{self.conversation_id}/claim",
            headers=self.support_headers,
            name="POST /api/v1/support/conversations/{id}/claim workflow",
        )
        if not claim.ok:
            return
        refund = self.client.post(
            f"/api/v1/support/conversations/{self.conversation_id}/refunds",
            headers=self.support_headers,
            json={
                "amount_cents": 2500,
                "reason": "Synthetic load review",
                "idempotency_key": f"locust-{self.conversation_id}",
            },
            name="POST /api/v1/support/conversations/{id}/refunds workflow",
        )
        if refund.ok:
            self.refund_id = refund.json()["refund_id"]
            self.workflow_ready = True

    def _login(self, actor_id: str, label: str):
        response = self.client.post(
            "/api/v1/auth/demo-login",
            json={"demo_actor_id": actor_id},
            name=f"POST /api/v1/auth/demo-login {label}",
        )
        if not response.ok:
            return {}
        return {"Authorization": f"Bearer {response.json()['session_id']}"}

    @task
    def review_and_verify_refund(self):
        if not self.workflow_ready or self.refund_id is None:
            return
        refunds = self.client.get(
            "/api/v1/refunds",
            headers=self.approver_headers,
            name="GET /api/v1/refunds workflow",
        )
        if refunds.ok and not self.refund_decided:
            self.client.post(
                f"/api/v1/refunds/{self.refund_id}/reject",
                headers=self.approver_headers,
                json={"note": "Synthetic load verification"},
                name="POST /api/v1/refunds/{id}/reject workflow",
            )
            self.refund_decided = True


class SyntheticWorkspaceUser(HttpUser):
    """Exercise authorized staff dashboard and knowledge reads."""

    wait_time = between(0.2, 0.8)

    def on_start(self):
        response = self.client.post(
            "/api/v1/auth/demo-login",
            json={"demo_actor_id": "merchant_admin_001"},
            name="POST /api/v1/auth/demo-login workspace",
        )
        self.authorization = (
            {"Authorization": f"Bearer {response.json()['session_id']}"}
            if response.ok
            else {}
        )

    @task(3)
    def operations_summary(self):
        self.client.get(
            "/api/v1/ops/summary",
            headers=self.authorization,
            name="GET /api/v1/ops/summary",
        )

    @task(2)
    def knowledge_catalog(self):
        self.client.get(
            "/api/v1/knowledge/policies?q=delivery&status=published&visibility=public",
            headers=self.authorization,
            name="GET /api/v1/knowledge/policies",
        )

    @task
    def workspace_settings(self):
        self.client.get(
            "/api/v1/workspace/settings",
            headers=self.authorization,
            name="GET /api/v1/workspace/settings",
        )


class SyntheticHealthUser(HttpUser):
    """Exercise public health/readiness probes during longer local runs."""

    wait_time = between(0.5, 1.0)

    @task(3)
    def health(self):
        self.client.get("/healthz", name="GET /healthz")

    @task
    def readiness(self):
        self.client.get("/readyz", name="GET /readyz")
