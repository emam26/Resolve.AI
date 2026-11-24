"""Bounded synthetic ResolveAI load, stress, and soak profiles for Locust.

This file targets only a locally running ResolveAI API.  It uses the fixed
synthetic demo identities and never contacts a real commerce, payment, model,
or external customer service.  Select a profile with
``RESOLVEAI_LOCUST_PROFILE=load|stress|soak``.
"""

from __future__ import annotations

import os
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from locust import HttpUser, LoadTestShape, between, events, task


PROFILE_STAGES = {
    "load": ((60, 8, 2), (120, 12, 2)),
    "stress": ((30, 20, 10), (90, 40, 10)),
    "soak": ((60, 8, 2), (600, 8, 1)),
}


# Locust already reports latency percentiles and failures.  These listeners add
# the small amount of workload metadata that is otherwise easy to lose when a
# run is summarized, without requiring a metrics service or changing the API.
_OBSERVATION_LOCK = threading.Lock()
_OBSERVATION: dict[str, object] = {}
_OBSERVATION_ENVIRONMENT = None


@events.test_start.add_listener
def _start_observation(environment) -> None:
    global _OBSERVATION_ENVIRONMENT
    _OBSERVATION_ENVIRONMENT = environment
    with _OBSERVATION_LOCK:
        _OBSERVATION.clear()
        _OBSERVATION.update(
            {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "started_monotonic": time.monotonic(),
                "requests": 0,
                "failures": 0,
                "request_names": {},
                "failure_kinds": {},
                "max_simulated_users": 0,
                "provider_distribution": None,
                "quota_contention": None,
                "fallback_count": None,
                "telemetry_unavailable": [
                    "application_cpu_memory",
                    "database_connections",
                    "queue_depth",
                    "provider_saturation",
                    "recovery_time",
                ],
            }
        )


@events.request.add_listener
def _observe_request(name, exception, context, **kwargs) -> None:
    # The request event is emitted after each request.  ``runner.user_count``
    # is an honest upper bound for simulated concurrency; exact application
    # in-flight counts require application-side telemetry and are not guessed.
    environment = kwargs.get("environment") or _OBSERVATION_ENVIRONMENT
    user_count = getattr(getattr(environment, "runner", None), "user_count", 0)
    context = context if isinstance(context, dict) else {}
    with _OBSERVATION_LOCK:
        _OBSERVATION["requests"] = int(_OBSERVATION.get("requests", 0)) + 1
        if exception is not None:
            _OBSERVATION["failures"] = int(_OBSERVATION.get("failures", 0)) + 1
            failures = _OBSERVATION.setdefault("failure_kinds", {})
            if isinstance(failures, dict):
                key = type(exception).__name__
                failures[key] = int(failures.get(key, 0)) + 1
        names = _OBSERVATION.setdefault("request_names", {})
        if isinstance(names, dict):
            names[name] = int(names.get(name, 0)) + 1
        _OBSERVATION["max_simulated_users"] = max(
            int(_OBSERVATION.get("max_simulated_users", 0)), int(user_count or 0)
        )
        for field in ("provider", "quota_contention", "fallback"):
            value = context.get(field)
            if field == "provider" and value:
                if _OBSERVATION.get("provider_distribution") is None:
                    _OBSERVATION["provider_distribution"] = {}
                distribution = _OBSERVATION["provider_distribution"]
                if isinstance(distribution, dict):
                    distribution[str(value)] = int(distribution.get(str(value), 0)) + 1
            elif field == "quota_contention" and value:
                _OBSERVATION["quota_contention"] = int(
                    _OBSERVATION.get("quota_contention") or 0
                ) + 1
            elif field == "fallback" and value:
                _OBSERVATION["fallback_count"] = int(
                    _OBSERVATION.get("fallback_count") or 0
                ) + 1


@events.test_stop.add_listener
def _finish_observation(environment, **kwargs) -> None:
    with _OBSERVATION_LOCK:
        observation = dict(_OBSERVATION)
        started = float(observation.pop("started_monotonic", time.monotonic()))
    observation["finished_at"] = datetime.now(timezone.utc).isoformat()
    observation["duration_seconds"] = round(max(0.0, time.monotonic() - started), 3)
    observation["profile"] = os.getenv("RESOLVEAI_LOCUST_PROFILE", "load").casefold()
    observation["max_seconds"] = os.getenv("RESOLVEAI_LOCUST_MAX_SECONDS")
    observation["concurrency_note"] = (
        "max_simulated_users is an upper bound; exact in-flight application "
        "telemetry was not available in this harness"
    )
    unavailable = set(observation.get("telemetry_unavailable", []))
    for field, label in (
        ("provider_distribution", "provider_distribution"),
        ("quota_contention", "quota_contention"),
        ("fallback_count", "fallback_frequency"),
    ):
        if observation.get(field) is not None:
            unavailable.discard(label)
    observation["telemetry_unavailable"] = sorted(unavailable)
    destination = os.getenv("RESOLVEAI_LOCUST_METRICS_PATH")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(observation, indent=2, sort_keys=True), encoding="utf-8")
    print("RESOLVEAI_LOCUST_OBSERVATION=" + json.dumps(observation, sort_keys=True))


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
