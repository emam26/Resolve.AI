"""M15 managed-policy index contracts and opt-in PostgreSQL verification."""

from __future__ import annotations

from datetime import datetime, timezone
from math import nan, sqrt

import pytest
from sqlalchemy import delete, inspect, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.db.policies import PolicyRepository, PolicySection, PolicyVersionRow, StoredPolicyVersion
from backend.app.ai.answer import answer_from_published_policy
from backend.app.rag.fulltext import build_full_text_policy_query
from backend.app.rag.models import PolicyEvidence
from backend.app.rag.pgvector_store import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    ManagedPolicyIndexUpdater,
    PgVectorPolicyRetriever,
    PolicyEmbeddingRow,
    build_pgvector_policy_query,
)


def _vector(axis: int = 0, value: float = 1.0) -> list[float]:
    result = [0.0] * DEFAULT_EMBEDDING_DIMENSIONS
    result[axis] = value
    return result


def _policy(
    *,
    version_id: str = "pv_m15",
    document_id: str = "m15-policy",
    document_version: str = "v1",
    release_id: str = "release_m15_v1",
    visibility: str = "public",
    state: str = "PUBLISHED",
    is_active: bool = True,
    index_state: str = "READY",
    sections: tuple[tuple[str, str], ...] = (("Shipping", "Shipping guidance."),),
) -> StoredPolicyVersion:
    now = datetime.now(timezone.utc)
    from backend.app.db.policies import PolicySection

    return StoredPolicyVersion(
        version_id=version_id,
        document_id=document_id,
        document_version=document_version,
        title=document_id,
        visibility=visibility,
        release_id=release_id,
        state=state,
        is_active=is_active,
        revision=1,
        index_state=index_state,
        failure_reason=None,
        created_at=now,
        updated_at=now,
        effective_from=now,
        effective_to=None,
        content_hash="m15",
        sections=tuple(PolicySection(section, text) for section, text in sections),
    )


class _DeterministicManagedProvider:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            if self.invalid:
                vector = _vector()
                vector[-1] = nan
            else:
                vector = _vector(0 if "shipping" in text.casefold() else 1)
            vectors.append(vector)
        return vectors


class _LowScoreManagedProvider:
    """Return a deterministic 0.54 query/policy cosine for M16 coverage."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            if "return 30 days unused" in text.casefold():
                vector = _vector(383, 0.54)
                vector[382] = sqrt(1.0 - 0.54**2)
            else:
                vector = _vector(383)
            vectors.append(vector)
        return vectors


class _NoTransactionEngine:
    def begin(self):
        raise AssertionError("invalid embeddings must be rejected before a transaction")


def test_managed_updater_validates_finite_384_vectors_before_writing() -> None:
    updater = ManagedPolicyIndexUpdater(
        embedding_provider=_DeterministicManagedProvider(invalid=True),
        engine=_NoTransactionEngine(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="finite"):
        updater(_policy())


def test_managed_and_legacy_query_paths_require_safe_state_filters() -> None:
    statements = (
        build_pgvector_policy_query(_vector(), top_k=3),
        build_full_text_policy_query("shipping", top_k=3),
    )
    for statement in statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        lowered = sql.lower()
        assert "policy_embeddings.version_id" in lowered
        assert "policy_versions.state" in lowered
        assert "policy_versions.is_active" in lowered
        assert "policy_versions.index_state" in lowered
        params = {str(value).lower() for value in compiled.params.values()}
        assert "published" in params
        assert "ready" in params
        assert "is null" in lowered  # legacy version_id=NULL branch


@pytest.fixture()
def managed_postgres_engine():
    import os
    from sqlalchemy import create_engine

    database_url = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("set RESOLVEAI_TEST_POSTGRES_URL for managed pgvector tests")
    engine = create_engine(database_url, future=True)
    columns = {item["name"] for item in inspect(engine).get_columns("policy_embeddings")}
    tables = set(inspect(engine).get_table_names())
    if "version_id" not in columns or "policy_versions" not in tables:
        engine.dispose()
        pytest.skip("M15 policy_embeddings.version_id and M14 policy_versions are required")

    _cleanup_managed(engine)
    try:
        yield engine
    finally:
        _cleanup_managed(engine)
        engine.dispose()


def _cleanup_managed(engine) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            delete(PolicyEmbeddingRow).where(
                PolicyEmbeddingRow.document_id.like("m15-%")
            )
        )
        session.execute(
            delete(PolicyVersionRow).where(PolicyVersionRow.document_id.like("m15-%"))
        )


def _insert_version(engine, policy: StoredPolicyVersion) -> None:
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        session.add(
            PolicyVersionRow(
                version_id=policy.version_id,
                document_id=policy.document_id,
                document_version=policy.document_version,
                title=policy.title,
                visibility=policy.visibility,
                release_id=policy.release_id,
                state=policy.state,
                is_active=policy.is_active,
                revision=policy.revision,
                index_state=policy.index_state,
                failure_reason=None,
                created_at=now,
                updated_at=now,
                effective_from=now,
                effective_to=None,
                content_hash=policy.content_hash,
            )
        )


def _retriever(engine, provider: _DeterministicManagedProvider) -> PgVectorPolicyRetriever:
    database_url = engine.url.render_as_string(hide_password=False)
    return PgVectorPolicyRetriever(database_url, provider, minimum_score=0.99)


def test_managed_updater_is_idempotent_and_customer_path_observes_only_active_version(
    managed_postgres_engine,
) -> None:
    engine = managed_postgres_engine
    old = _policy(
        version_id="pv_m15_old",
        document_version="v1",
        release_id="release_m15_old",
        state="UNPUBLISHED",
        is_active=False,
        index_state="NOT_INDEXED",
    )
    current = _policy(
        version_id="pv_m15_current",
        document_version="v2",
        release_id="release_m15_current",
    )
    _insert_version(engine, old)
    _insert_version(engine, current)
    updater = ManagedPolicyIndexUpdater(
        embedding_provider=_DeterministicManagedProvider(), engine=engine
    )
    assert updater(old) == "READY"
    assert updater(current) == "READY"
    assert updater(current) == "READY"

    with Session(engine) as session:
        rows = session.scalars(
            select(PolicyEmbeddingRow).where(
                PolicyEmbeddingRow.version_id == current.version_id
            )
        ).all()
        assert len(rows) == 1

    retriever = _retriever(engine, _DeterministicManagedProvider())
    try:
        results = retriever.retrieve_published_policy("m15 shipping")
        assert [(item.document_version, item.release_id) for item in results] == [
            ("v2", "release_m15_current")
        ]
        answer = answer_from_published_policy(
            "m15 shipping", policy_retriever=retriever
        )
        assert answer.grounded is True
        assert answer.needs_handoff is False
        assert answer.evidence[0].document_version == "v2"

        with Session(engine) as session, session.begin():
            session.execute(
                update(PolicyVersionRow)
                .where(PolicyVersionRow.version_id == current.version_id)
                .values(state="UNPUBLISHED", is_active=False, index_state="NOT_INDEXED")
            )
            session.execute(
                update(PolicyVersionRow)
                .where(PolicyVersionRow.version_id == old.version_id)
                .values(state="PUBLISHED", is_active=True, index_state="READY")
            )
        results = retriever.retrieve_published_policy("m15 shipping")
        assert [(item.document_version, item.release_id) for item in results] == [
            ("v1", "release_m15_old")
        ]
    finally:
        retriever.close()


def test_managed_updater_rejects_partial_invalid_refresh_without_deleting_previous_rows(
    managed_postgres_engine,
) -> None:
    engine = managed_postgres_engine
    policy = _policy(
        version_id="pv_m15_partial",
        document_id="m15-partial",
        sections=(("Shipping", "Shipping guidance."), ("Returns", "Return guidance.")),
    )
    _insert_version(engine, policy)
    updater = ManagedPolicyIndexUpdater(
        embedding_provider=_DeterministicManagedProvider(), engine=engine
    )
    assert updater(policy) == "READY"

    duplicate_sections = _policy(
        version_id=policy.version_id,
        document_id=policy.document_id,
        document_version=policy.document_version,
        release_id=policy.release_id,
        sections=(("Shipping", "Replacement shipping guidance."), ("Shipping", "Duplicate.")),
    )
    with pytest.raises(IntegrityError):
        updater(duplicate_sections)

    with pytest.raises(ValueError, match="finite"):
        ManagedPolicyIndexUpdater(
            embedding_provider=_DeterministicManagedProvider(invalid=True), engine=engine
        )(policy)

    with Session(engine) as session:
        rows = session.scalars(
            select(PolicyEmbeddingRow).where(
                PolicyEmbeddingRow.version_id == policy.version_id
            )
        ).all()
        assert len(rows) == 2


def test_customer_retrieval_excludes_internal_managed_policy_and_staff_can_see_it(
    managed_postgres_engine,
) -> None:
    engine = managed_postgres_engine
    policy = _policy(
        version_id="pv_m15_internal",
        document_id="m15-internal",
        release_id="release_m15_internal",
        visibility="internal",
    )
    _insert_version(engine, policy)
    ManagedPolicyIndexUpdater(
        embedding_provider=_DeterministicManagedProvider(), engine=engine
    )(policy)

    customer = _retriever(engine, _DeterministicManagedProvider())
    staff = PgVectorPolicyRetriever(
        engine.url.render_as_string(hide_password=False),
        _DeterministicManagedProvider(),
        minimum_score=0.99,
    )
    try:
        assert customer.retrieve_published_policy("m15 shipping", audience="customer") == []
        staff_results = staff.retrieve_published_policy(
            "m15 shipping", audience="support_agent"
        )
        assert [item.document_id for item in staff_results] == ["m15-internal"]
    finally:
        customer.close()
        staff.close()


def test_managed_published_policy_reaches_customer_api(
    managed_postgres_engine,
) -> None:
    engine = managed_postgres_engine
    database_url = engine.url.render_as_string(hide_password=False)
    provider = _DeterministicManagedProvider()
    updater = ManagedPolicyIndexUpdater(embedding_provider=provider, engine=engine)
    repository = PolicyRepository(
        engine=engine,
        initialize_schema=False,
        index_updater=updater,
    )
    draft = repository.create(
        actor_id="merchant_admin_001",
        document_id="m15-api-policy",
        document_version="v1",
        release_id="release_m15_api_v1",
        visibility="public",
        sections=[PolicySection(section="Shipping", text="M15 shipping guidance.")],
    )
    published = repository.publish(
        "m15-api-policy",
        "v1",
        actor_id="merchant_admin_001",
        expected_revision=draft.revision,
    )
    assert published.state == "PUBLISHED"

    retriever = _retriever(engine, provider)
    client = TestClient(
        create_app(
            database_url=database_url,
            policy_retriever=retriever,
            policy_index_updater=updater,
        )
    )
    try:
        login = client.post(
            "/api/v1/auth/demo-login",
            json={"demo_actor_id": "customer_001"},
        )
        headers = {"Authorization": f"Bearer {login.json()['session_id']}"}
        conversation = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"channel": "widget", "order_id": None},
        )
        response = client.post(
            f"/api/v1/conversations/{conversation.json()['conversation_id']}/messages",
            headers=headers,
            json={"content": "m15 shipping"},
        )

        assert login.status_code == 200
        assert conversation.status_code == 201
        assert response.status_code == 201
        body = response.json()
        assert body["retrieval_mode"] == "semantic"
        assert body["assistant_reply"]["content"] == "M15 shipping guidance."
        assert body["evidence"][0]["document_id"] == "m15-api-policy"
        assert body["evidence"][0]["document_version"] == "v1"
    finally:
        retriever.close()


def test_managed_customer_answer_uses_explicit_applicability_below_semantic_gate(
    managed_postgres_engine,
) -> None:
    engine = managed_postgres_engine
    policy = _policy(
        version_id="pv_m15_low_score",
        document_id="m15-m16-low-score",
        release_id="release_m15_m16_low_score",
        sections=(
            (
                "Return window",
                "A return request must be submitted within 30 calendar days. "
                "Items must be unused with original packaging.",
            ),
        ),
    )
    _insert_version(engine, policy)
    provider = _LowScoreManagedProvider()
    updater = ManagedPolicyIndexUpdater(embedding_provider=provider, engine=engine)
    assert updater(policy) == "READY"

    retriever = _retriever(engine, provider)
    try:
        answer = answer_from_published_policy(
            "return 30 days unused",
            policy_retriever=retriever,
        )
        assert answer.grounded is True
        assert answer.needs_handoff is False
        assert answer.evidence[0].score == pytest.approx(0.54, abs=0.001)
        assert answer.evidence[0].document_id == "m15-m16-low-score"
    finally:
        retriever.close()


def test_managed_evidence_keeps_frozen_transport_shape() -> None:
    evidence = PolicyEvidence(
        document_id="m15-policy",
        document_version="v1",
        section="Shipping",
        release_id="release_m15_v1",
        visibility="public",
        score=1.0,
        text="Shipping guidance.",
    )
    assert "version_id" not in evidence.model_dump(mode="json")
