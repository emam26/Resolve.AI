from __future__ import annotations

import os

import pytest

from backend.app.db.memory import CustomerMemoryRepository


@pytest.fixture()
def postgres_url() -> str:
    value = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("set RESOLVEAI_TEST_POSTGRES_URL for PostgreSQL memory checks")
    return value


def test_postgres_memory_survives_repository_restart_and_keeps_owner_scope(
    postgres_url: str,
) -> None:
    first = CustomerMemoryRepository(postgres_url, initialize_schema=False)
    stored = first.add(
        customer_id="customer_m19_pg",
        content="Synthetic continuity note.",
        provenance="conversation_summary",
    )

    restarted = CustomerMemoryRepository(postgres_url, initialize_schema=False)
    assert restarted.get(stored.memory_id, customer_id="customer_m19_pg") == stored
    assert restarted.get(stored.memory_id, customer_id="customer_other") is None
