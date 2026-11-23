from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from backend.app.db.conversations import create_database_engine
from backend.app.db.policies import (
    PolicyConflict,
    PolicyIndexJobRow,
    PolicyIndexUpdateError,
    PolicyDocumentRow,
    PolicyRepository,
    PolicySection,
    PolicyVersionRow,
)


def _repository(updater=None) -> PolicyRepository:
    return PolicyRepository(
        engine=create_database_engine("sqlite+pysqlite:///:memory:"),
        index_updater=updater,
    )


def _draft(repository: PolicyRepository, document_id: str = "m15-policy"):
    return repository.create(
        actor_id="merchant_admin_001",
        actor_role="merchant_admin",
        document_id=document_id,
        document_version="v1",
        release_id=f"release_{document_id}",
        visibility="public",
        sections=[PolicySection(section="Window", text="Returns are accepted within 30 days.")],
    )


def _jobs(
    repository: PolicyRepository,
    version_id: str | None = None,
) -> list[PolicyIndexJobRow]:
    with repository._session_factory() as session:  # noqa: SLF001 - focused persistence test
        statement = select(PolicyIndexJobRow).order_by(PolicyIndexJobRow.attempt)
        if version_id is not None:
            statement = statement.where(PolicyIndexJobRow.version_id == version_id)
        return list(
            session.scalars(statement).all()
        )


@pytest.fixture()
def postgres_url() -> str:
    value = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("set RESOLVEAI_TEST_POSTGRES_URL for PostgreSQL M15 checks")
    return value


def test_index_attempt_is_idempotent_and_persists_success() -> None:
    calls: list[str] = []

    def updater(policy):
        calls.append(policy.version_id)
        return "READY"

    repository = _repository(updater)
    draft = _draft(repository)

    indexed = repository.index(
        draft.version_id,
        actor_id="merchant_admin_001",
        idempotency_key="m15-attempt-1",
    )
    repeated = repository.index(
        draft.version_id,
        actor_id="merchant_admin_001",
        idempotency_key="m15-attempt-1",
    )

    assert indexed.state == repeated.state == "READY_FOR_TEST"
    assert calls == [draft.version_id]
    jobs = _jobs(repository, draft.version_id)
    assert [(job.attempt, job.state, job.idempotency_key) for job in jobs] == [
        (1, "SUCCEEDED", "m15-attempt-1")
    ]


def test_callback_failure_is_durable_and_retry_uses_next_attempt() -> None:
    should_fail = True

    def updater(_policy):
        nonlocal should_fail
        if should_fail:
            raise RuntimeError("synthetic vector failure")
        return "READY"

    repository = _repository(updater)
    draft = _draft(repository, "m15-retry")
    with pytest.raises(PolicyIndexUpdateError):
        repository.index(draft.version_id, actor_id="merchant_admin_001")

    failed = repository.get_by_id(draft.version_id)
    assert failed is not None
    assert (failed.state, failed.index_state) == ("FAILED", "UNAVAILABLE")
    assert _jobs(repository)[0].state == "FAILED"
    assert _jobs(repository)[0].failure_reason == "policy index updater failed"

    should_fail = False
    recovered = repository.index(draft.version_id, actor_id="merchant_admin_001")
    assert (recovered.state, recovered.index_state) == ("READY_FOR_TEST", "READY")
    assert [(job.attempt, job.state) for job in _jobs(repository)] == [
        (1, "FAILED"),
        (2, "SUCCEEDED"),
    ]


def test_restart_marks_running_job_interrupted_and_version_failed() -> None:
    repository = _repository(lambda _policy: "READY")
    draft = _draft(repository, "m15-restart")
    now = datetime.now(timezone.utc)
    with repository._session_factory.begin() as session:  # noqa: SLF001
        row = session.get(PolicyVersionRow, draft.version_id)
        assert row is not None
        row.state = "INDEXING"
        row.index_state = "NOT_INDEXED"
        session.add(
            PolicyIndexJobRow(
                job_id="pij_m15_interrupted",
                version_id=draft.version_id,
                attempt=1,
                state="RUNNING",
                actor_id="merchant_admin_001",
                actor_role="merchant_admin",
                idempotency_key=None,
                failure_reason=None,
                created_at=now,
                started_at=now,
                finished_at=None,
            )
        )

    restarted = PolicyRepository(engine=repository.engine, index_updater=lambda _policy: "READY")
    recovered = restarted.get_by_id(draft.version_id)
    assert recovered is not None
    assert (recovered.state, recovered.index_state) == ("FAILED", "FAILED")
    job = _jobs(restarted)[0]
    assert (job.state, job.failure_reason) == ("INTERRUPTED", "indexing interrupted; restart required")
    events = restarted.audits(document_id="m15-restart", document_version="v1")
    recovery = next(event for event in events if event.action == "RECOVER_INDEX")
    assert recovery.metadata["interrupted_jobs"] == ["pij_m15_interrupted"]


def test_stale_revision_cannot_repeat_completed_attempt() -> None:
    repository = _repository(lambda _policy: "READY")
    draft = _draft(repository, "m15-stale")
    indexed = repository.index(draft.version_id, actor_id="merchant_admin_001")
    with pytest.raises(PolicyConflict) as error:
        repository.index(
            draft.version_id,
            actor_id="merchant_admin_001",
            expected_revision=draft.revision,
        )
    assert "stale policy revision" in str(error.value)
    assert indexed.revision > draft.revision


def test_direct_publish_records_the_durable_index_attempt() -> None:
    repository = _repository(lambda _policy: "READY")
    draft = _draft(repository, "m15-direct-publish")

    published = repository.publish(
        "m15-direct-publish",
        "v1",
        actor_id="merchant_admin_001",
        expected_revision=draft.revision,
    )

    assert published.state == "PUBLISHED"
    jobs = _jobs(repository, draft.version_id)
    assert len(jobs) == 1
    assert (jobs[0].state, jobs[0].version_id) == ("SUCCEEDED", published.version_id)


def test_rollback_indexes_the_target_before_activation() -> None:
    repository = _repository(lambda _policy: "READY")
    first = _draft(repository, "m15-direct-rollback")
    first = repository.publish(
        "m15-direct-rollback",
        "v1",
        actor_id="merchant_admin_001",
        expected_revision=first.revision,
    )
    second = repository.create(
        actor_id="merchant_admin_001",
        document_id="m15-direct-rollback",
        document_version="v2",
        release_id="release_m15_direct_rollback_v2",
        visibility="public",
        sections=[PolicySection(section="Window", text="Returns are accepted within 45 days.")],
    )
    second = repository.publish(
        "m15-direct-rollback",
        "v2",
        actor_id="merchant_admin_001",
        expected_revision=second.revision,
    )

    rolled_back = repository.rollback(
        "m15-direct-rollback",
        "v2",
        target_version="v1",
        actor_id="merchant_admin_001",
        actor_role="merchant_admin",
        expected_revision=second.revision,
    )

    assert rolled_back.state == "PUBLISHED"
    assert rolled_back.document_version == "v1"
    assert len(_jobs(repository)) == 3


def test_postgres_index_jobs_are_durable_idempotent_and_restart_recoverable(
    postgres_url: str,
) -> None:
    prefix = f"m15-pg-job-{uuid4().hex[:10]}"
    repository = PolicyRepository(
        database_url=postgres_url,
        initialize_schema=False,
        index_updater=lambda _policy: "READY",
    )
    draft = _draft(repository, prefix)
    indexed = repository.index(
        draft.version_id,
        actor_id="merchant_admin_001",
        idempotency_key="m15-pg-attempt-1",
    )
    repeated = repository.index(
        draft.version_id,
        actor_id="merchant_admin_001",
        idempotency_key="m15-pg-attempt-1",
    )
    assert indexed.state == repeated.state == "READY_FOR_TEST"
    jobs = _jobs(repository, draft.version_id)
    assert [(job.state, job.attempt, job.idempotency_key) for job in jobs] == [
        ("SUCCEEDED", 1, "m15-pg-attempt-1")
    ]

    interrupted = _draft(repository, f"{prefix}-restart")
    now = datetime.now(timezone.utc)
    with repository._session_factory.begin() as session:  # noqa: SLF001
        row = session.get(PolicyVersionRow, interrupted.version_id)
        assert row is not None
        row.state = "INDEXING"
        row.index_state = "NOT_INDEXED"
        session.add(
            PolicyIndexJobRow(
                job_id=f"pij_{uuid4().hex}",
                version_id=interrupted.version_id,
                attempt=1,
                state="RUNNING",
                actor_id="merchant_admin_001",
                actor_role="merchant_admin",
                idempotency_key=None,
                failure_reason=None,
                created_at=now,
                started_at=now,
                finished_at=None,
            )
        )

    restarted = PolicyRepository(
        database_url=postgres_url,
        initialize_schema=False,
        index_updater=lambda _policy: "READY",
    )
    recovered = restarted.get_by_id(interrupted.version_id)
    assert recovered is not None
    assert (recovered.state, recovered.index_state) == ("FAILED", "FAILED")
    with restarted._session_factory() as session:  # noqa: SLF001
        job = session.scalar(
            select(PolicyIndexJobRow).where(
                PolicyIndexJobRow.version_id == interrupted.version_id
            )
        )
    assert job is not None
    assert (job.state, job.failure_reason) == (
        "INTERRUPTED",
        "indexing interrupted; restart required",
    )

    with restarted._session_factory.begin() as session:  # noqa: SLF001
        session.execute(
            delete(PolicyVersionRow).where(
                PolicyVersionRow.document_id.like(f"{prefix}%")
            )
        )
        session.execute(
            delete(PolicyDocumentRow).where(
                PolicyDocumentRow.document_id.like(f"{prefix}%")
            )
        )
    restarted.engine.dispose()
    if repository.engine is not restarted.engine:
        repository.engine.dispose()


def test_postgres_concurrent_index_workers_publish_one_durable_attempt(
    postgres_url: str,
) -> None:
    prefix = f"m15-pg-concurrent-{uuid4().hex[:10]}"
    creator = PolicyRepository(
        database_url=postgres_url,
        initialize_schema=False,
        index_updater=lambda _policy: "READY",
    )
    draft = _draft(creator, prefix)
    start = Barrier(2)

    def run_worker() -> str:
        worker = PolicyRepository(
            database_url=postgres_url,
            initialize_schema=False,
            index_updater=lambda _policy: "READY",
        )
        try:
            start.wait(timeout=10)
            return worker.index(
                draft.version_id,
                actor_id="merchant_admin_001",
                idempotency_key="m15-concurrent-attempt",
            ).state
        finally:
            worker.engine.dispose()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _item: run_worker(), (1, 2)))

        assert results == ["READY_FOR_TEST", "READY_FOR_TEST"]
        jobs = _jobs(creator, draft.version_id)
        assert len(jobs) == 1
        assert (jobs[0].state, jobs[0].attempt) == ("SUCCEEDED", 1)
    finally:
        with creator._session_factory.begin() as session:  # noqa: SLF001
            session.execute(
                delete(PolicyVersionRow).where(
                    PolicyVersionRow.document_id == prefix
                )
            )
            session.execute(
                delete(PolicyDocumentRow).where(
                    PolicyDocumentRow.document_id == prefix
                )
            )
        creator.engine.dispose()
