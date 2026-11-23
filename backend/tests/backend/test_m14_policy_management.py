from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from backend.app.api import create_app
from backend.app.db import PolicyConflict, PolicyRepository, PolicySection, PolicyVersionRow
from backend.app.db.conversations import create_database_engine


def _login(client: TestClient, actor_id: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/demo-login", json={"demo_actor_id": actor_id})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['session_id']}"}


def _local_client() -> TestClient:
    """Keep local lifecycle tests isolated from an externally supplied PG DB."""

    return TestClient(
        create_app(
            database_url="sqlite+pysqlite:///:memory:",
            policy_index_updater=lambda _policy: "READY",
        )
    )


def _failing_index(_policy):
    raise RuntimeError("synthetic index failure")


def _draft(client: TestClient, headers: dict[str, str], version: str | None = None):
    payload = {
        "document_id": "m14-returns",
        "title": "Returns policy",
        "visibility": "public",
        "sections": [{"section": "Window", "text": "Returns are accepted within 30 days."}],
    }
    if version:
        payload["document_version"] = version
    return client.post("/api/v1/knowledge/policies", headers=headers, json=payload)


@pytest.fixture()
def postgres_url() -> str:
    value = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("set RESOLVEAI_TEST_POSTGRES_URL to an Alembic-migrated PostgreSQL database")
    return value


def test_policy_mutations_split_draft_authority_from_release_authority() -> None:
    client = _local_client()
    support = _login(client, "support_001")
    approver = _login(client, "refund_approver_001")
    customer = _login(client, "customer_001")
    admin = _login(client, "merchant_admin_001")

    assert client.post(
        "/api/v1/knowledge/policies",
        json={
            "document_id": "m14-returns",
            "title": "Returns policy",
            "visibility": "public",
            "sections": [{"section": "Window", "text": "Thirty days."}],
        },
    ).status_code == 401
    for headers in (support, approver, customer):
        assert _draft(client, headers).status_code == 403
    support_draft = client.post(
        "/api/v1/knowledge/policies",
        headers=support,
        json={
            "document_id": "m14-release-alias",
            "document_version": "v1",
            "release_id": "release_alias_v1",
            "visibility": "public",
            "sections": [{"section": "Window", "text": "Thirty days."}],
        },
    )
    assert support_draft.status_code == 201
    assert support_draft.json()["state"] == "DRAFT"
    edited_support_draft = client.put(
        "/api/v1/knowledge/policies/m14-release-alias/v1",
        headers=support,
        json={
            "expected_revision": 1,
            "release_id": "release_alias_v1",
            "visibility": "public",
            "sections": [{"section": "Window", "text": "Forty-five days."}],
        },
    )
    assert edited_support_draft.status_code == 200
    assert edited_support_draft.json()["revision"] == 2
    assert client.post(
        "/api/v1/knowledge/policies/m14-release-alias/v1/publish",
        headers=support,
        json={"expected_revision": 2},
    ).status_code == 403
    created = _draft(client, admin)
    assert created.status_code == 201
    assert created.json()["state"] == "DRAFT"
    assert client.get("/api/v1/knowledge/audit", headers=support).status_code == 403
    audit = client.get("/api/v1/knowledge/audit?document_id=m14-returns", headers=admin)
    assert audit.status_code == 200
    assert audit.json()["events"]
    assert all(event["revision"] is not None for event in audit.json()["events"])


def test_edit_validation_and_stale_revision_conflict() -> None:
    client = _local_client()
    admin = _login(client, "merchant_admin_001")
    created = _draft(client, admin).json()
    version_id = created["version_id"]

    edited = client.patch(
        f"/api/v1/knowledge/policies/{version_id}",
        headers=admin,
        json={
            "expected_revision": 1,
            "title": "Updated returns policy",
            "release_id": "release_m14_updated",
            "sections": [{"section": "Window", "text": "Returns are accepted within 45 days."}],
        },
    )
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2
    assert edited.json()["release_id"] == "release_m14_updated"
    stale = client.patch(
        f"/api/v1/knowledge/policies/{version_id}",
        headers=admin,
        json={"expected_revision": 1, "title": "Stale write"},
    )
    assert stale.status_code == 409

    invalid = client.patch(
        f"/api/v1/knowledge/policies/{version_id}",
        headers=admin,
        json={"expected_revision": 2, "sections": [{"section": "Window", "text": ""}]},
    )
    assert invalid.status_code == 422
    validation = client.post(f"/api/v1/knowledge/policies/{version_id}/validate", headers=admin)
    assert validation.status_code == 200
    assert validation.json()["valid"] is True


def test_index_publish_and_customer_safe_catalog_boundaries() -> None:
    client = _local_client()
    admin = _login(client, "merchant_admin_001")
    customer = _login(client, "customer_001")
    created = _draft(client, admin).json()
    version_id = created["version_id"]
    indexed = client.post(f"/api/v1/knowledge/policies/{version_id}/index", headers=admin)
    assert indexed.status_code == 200
    assert indexed.json()["state"] == "READY_FOR_TEST"
    published = client.post(f"/api/v1/knowledge/policies/{version_id}/publish", headers=admin)
    assert published.status_code == 200
    assert published.json()["state"] == "PUBLISHED"
    assert published.json()["is_active"] is True
    assert client.get("/api/v1/knowledge/policies", headers=customer).status_code == 403
    listed = client.get("/api/v1/knowledge/policies", headers=admin)
    assert listed.status_code == 200
    assert any(item.get("version_id") == version_id for item in listed.json()["policies"])


def test_publish_is_idempotent_and_rollback_activates_one_version() -> None:
    client = _local_client()
    admin = _login(client, "merchant_admin_001")
    first = _draft(client, admin, "v1").json()
    client.post(f"/api/v1/knowledge/policies/{first['version_id']}/index", headers=admin)
    published_first = client.post(f"/api/v1/knowledge/policies/{first['version_id']}/publish", headers=admin)
    assert published_first.status_code == 200
    repeated = client.post(f"/api/v1/knowledge/policies/{first['version_id']}/publish", headers=admin)
    assert repeated.status_code == 200
    assert repeated.json()["release_id"] == published_first.json()["release_id"]

    second = _draft(client, admin, "v2").json()
    client.post(f"/api/v1/knowledge/policies/{second['version_id']}/index", headers=admin)
    assert client.post(f"/api/v1/knowledge/policies/{second['version_id']}/publish", headers=admin).status_code == 200
    rollback = client.post(
        "/api/v1/knowledge/policies/m14-returns/rollback",
        headers=admin,
        json={"document_version": "v1"},
    )
    assert rollback.status_code == 200
    assert rollback.json()["document_version"] == "v1"
    versions = client.get("/api/v1/knowledge/policies/m14-returns/versions", headers=admin).json()["versions"]
    assert sum(item["is_active"] for item in versions) == 1
    events = client.get("/api/v1/knowledge/audit?document_id=m14-returns", headers=admin).json()["events"]
    assert any(event["action"] == "ROLLBACK" for event in events)


def test_restart_recovers_interrupted_indexing_and_preserves_audit() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    repository = PolicyRepository(engine=engine)
    draft = repository.create(
        actor_id="merchant_admin_001",
        actor_role="merchant_admin",
        document_id="restart-policy",
        document_version="v1",
        release_id="release_restart_v1",
        visibility="public",
        sections=[PolicySection(section="Window", text="Thirty days.")],
    )
    with engine.begin() as connection:
        connection.execute(update(PolicyVersionRow).where(PolicyVersionRow.version_id == draft.version_id).values(state="INDEXING"))
    restarted = PolicyRepository(engine=engine)
    recovered = restarted.get_by_id(draft.version_id)
    assert recovered is not None
    assert recovered.state == "FAILED"
    assert any(item.action == "RECOVER_INDEX" for item in restarted.audits(document_id="restart-policy", document_version="v1"))


def test_index_without_updater_fails_closed_and_callback_errors_are_structured() -> None:
    unavailable = TestClient(create_app(database_url="sqlite+pysqlite:///:memory:"))
    admin = _login(unavailable, "merchant_admin_001")
    created = _draft(unavailable, admin).json()
    indexed = unavailable.post(
        f"/api/v1/knowledge/policies/{created['version_id']}/index", headers=admin
    )
    assert indexed.status_code == 200
    assert indexed.json()["state"] == "FAILED"
    assert unavailable.post(
        f"/api/v1/knowledge/policies/{created['version_id']}/publish", headers=admin
    ).status_code == 409

    failing = TestClient(
        create_app(
            database_url="sqlite+pysqlite:///:memory:",
            policy_index_updater=_failing_index,
        )
    )
    failing_admin = _login(failing, "merchant_admin_001")
    draft = _draft(failing, failing_admin).json()
    response = failing.post(
        f"/api/v1/knowledge/policies/{draft['version_id']}/index",
        headers=failing_admin,
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "policy_index_unavailable"

    # Compatibility aliases must preserve the same fail-closed contract; a
    # callback failure must not escape as an unhandled 500.
    legacy_admin = _login(failing, "merchant_admin_001")
    legacy = failing.post(
        "/api/v1/knowledge/policies",
        headers=legacy_admin,
        json={
            "document_id": "m14-legacy-failure",
            "document_version": "v1",
            "release_id": "release_legacy_failure_v1",
            "visibility": "public",
            "sections": [{"section": "Window", "text": "Thirty days."}],
        },
    )
    assert legacy.status_code == 201
    legacy_publish = failing.post(
        "/api/v1/knowledge/policies/m14-legacy-failure/v1/publish",
        headers=legacy_admin,
        json={"expected_revision": legacy.json()["revision"]},
    )
    assert legacy_publish.status_code == 503
    assert legacy_publish.json()["error"]["code"] == "policy_index_unavailable"


def test_rollback_unavailable_target_preserves_active_version() -> None:
    index_available = True

    def updater(_policy):
        return "READY" if index_available else "UNAVAILABLE"

    repository = PolicyRepository(
        engine=create_database_engine("sqlite+pysqlite:///:memory:"),
        index_updater=updater,
    )
    first = repository.create(
        actor_id="merchant_admin_001",
        actor_role="merchant_admin",
        document_id="rollback-safe",
        document_version="v1",
        release_id="release_v1",
        visibility="public",
        sections=[PolicySection(section="Window", text="Thirty days.")],
    )
    first = repository.index(first.version_id, actor_id="merchant_admin_001")
    first = repository.publish("rollback-safe", "v1", actor_id="merchant_admin_001", expected_revision=first.revision)
    second = repository.create(
        actor_id="merchant_admin_001",
        actor_role="merchant_admin",
        document_id="rollback-safe",
        document_version="v2",
        release_id="release_v2",
        visibility="public",
        sections=[PolicySection(section="Window", text="Forty-five days.")],
    )
    second = repository.index(second.version_id, actor_id="merchant_admin_001")
    second = repository.publish("rollback-safe", "v2", actor_id="merchant_admin_001", expected_revision=second.revision)
    index_available = False
    with pytest.raises(PolicyConflict):
        repository.rollback(
            "rollback-safe",
            "v2",
            target_version="v1",
            actor_id="merchant_admin_001",
            actor_role="merchant_admin",
            expected_revision=second.revision,
        )
    assert repository.get("rollback-safe", "v2").is_active is True
    assert repository.get("rollback-safe", "v1").is_active is False


def test_release_aware_document_version_contract_allows_support_drafts() -> None:
    client = _local_client()
    support = _login(client, "support_001")
    response = client.post(
        "/api/v1/knowledge/policies",
        headers=support,
        json={
            "document_id": "m14-contract",
            "document_version": "v1",
            "release_id": "release_m14_contract_v1",
            "visibility": "public",
            "sections": [{"section": "Window", "text": "Returns are accepted within 30 days."}],
        },
    )
    assert response.status_code == 201
    assert response.json()["state"] == "DRAFT"


def test_postgres_policy_lifecycle_persists_across_restart(postgres_url: str) -> None:
    document_id = f"m14-pg-{uuid4().hex[:12]}"
    first = TestClient(
        create_app(database_url=postgres_url, policy_index_updater=lambda _policy: "READY")
    )
    admin = _login(first, "merchant_admin_001")
    created = first.post(
        "/api/v1/knowledge/policies",
        headers=admin,
        json={
            "document_id": document_id,
            "title": "PostgreSQL policy",
            "visibility": "public",
            "sections": [{"section": "Window", "text": "Returns are accepted within 30 days."}],
        },
    )
    assert created.status_code == 201
    version_id = created.json()["version_id"]
    assert first.post(f"/api/v1/knowledge/policies/{version_id}/index", headers=admin).status_code == 200
    published = first.post(f"/api/v1/knowledge/policies/{version_id}/publish", headers=admin)
    assert published.status_code == 200
    assert published.json()["is_active"] is True

    second = TestClient(
        create_app(database_url=postgres_url, policy_index_updater=lambda _policy: "READY")
    )
    restored_admin = _login(second, "merchant_admin_001")
    versions = second.get(f"/api/v1/knowledge/policies/{document_id}/versions", headers=restored_admin)
    assert versions.status_code == 200
    assert versions.json()["versions"][0]["state"] == "PUBLISHED"


def test_postgres_concurrent_policy_edits_allow_one_revision_winner(postgres_url: str) -> None:
    document_id = f"m14-race-{uuid4().hex[:12]}"
    repository = PolicyRepository(database_url=postgres_url, initialize_schema=False)
    draft = repository.create(
        actor_id="merchant_admin_001",
        actor_role="merchant_admin",
        document_id=document_id,
        document_version="v1",
        release_id=f"release_{document_id}",
        visibility="public",
        sections=[PolicySection(section="Window", text="Thirty days.")],
    )
    repository.engine.dispose()

    def edit(text: str):
        worker = PolicyRepository(database_url=postgres_url, initialize_schema=False)
        try:
            worker.update_draft(
                document_id,
                "v1",
                actor_id="merchant_admin_001",
                actor_role="merchant_admin",
                expected_revision=draft.revision,
                release_id=f"release_{document_id}",
                visibility="public",
                sections=[PolicySection(section="Window", text=text)],
            )
            return "ok"
        except PolicyConflict:
            return "conflict"
        finally:
            worker.engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(edit, ("Forty-five days.", "Sixty days.")))

    assert sorted(results) == ["conflict", "ok"]
