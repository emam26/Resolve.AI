from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from backend.app.ai.model_control import QuotaExceeded, QuotaLedger


@pytest.fixture
def postgres_url() -> str:
    value = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not value or not value.startswith(("postgresql", "postgres")):
        pytest.skip("set RESOLVEAI_TEST_POSTGRES_URL for PostgreSQL M18-FIX checks")
    return value


def test_postgres_shared_experiment_budget_persists_across_restart(postgres_url: str) -> None:
    experiment = f"pg-{uuid4().hex}"
    reset_at = datetime.now(timezone.utc) + timedelta(hours=1)
    ledger = QuotaLedger(postgres_url)
    scope = ledger.configure_experiment(
        experiment,
        request_limit=2,
        token_limit=30,
        concurrency_limit=1,
        reset_at=reset_at,
    )
    reservation = ledger.reserve(scope, 20)
    ledger.complete(reservation, 20)

    restarted = QuotaLedger(postgres_url)
    assert restarted.snapshot(scope).requests_used == 1
    assert restarted.snapshot(scope).tokens_used == 20
    with pytest.raises(QuotaExceeded, match="token"):
        restarted.reserve(scope, 11)


def test_postgres_concurrent_reservations_do_not_oversubscribe_shared_budget(
    postgres_url: str,
) -> None:
    experiment = f"pg-concurrent-{uuid4().hex}"
    reset_at = datetime.now(timezone.utc) + timedelta(hours=1)
    setup = QuotaLedger(postgres_url)
    scope = setup.configure_experiment(
        experiment,
        request_limit=4,
        token_limit=40,
        concurrency_limit=4,
        reset_at=reset_at,
    )

    def reserve_one() -> bool:
        ledger = QuotaLedger(postgres_url)
        try:
            reservation = ledger.reserve(scope, 10)
            ledger.complete(reservation, 10)
            return True
        except QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: reserve_one(), range(8)))

    snapshot = QuotaLedger(postgres_url).snapshot(scope)
    assert sum(outcomes) == 4
    assert snapshot.requests_used == 4
    assert snapshot.tokens_used == 40
    assert snapshot.in_flight == 0
