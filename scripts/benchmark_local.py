"""Small synthetic local API baseline for ResolveAI.

This benchmark is intentionally bounded and in-process. It measures the
existing FastAPI application with SQLite-backed synthetic records; it does not
start a server, touch Docker, or call external services.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from backend.app.api import create_app


@dataclass(frozen=True)
class Sample:
    elapsed_ms: float
    status_code: int


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def _summary(samples: list[Sample], elapsed_seconds: float) -> dict[str, Any]:
    latencies = [sample.elapsed_ms for sample in samples]
    failures = sum(sample.status_code >= 400 for sample in samples)
    return {
        "requests": len(samples),
        "p50_ms": round(_percentile(latencies, 0.50), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
        "p99_ms": round(_percentile(latencies, 0.99), 3),
        "requests_per_second": round(
            len(samples) / elapsed_seconds if elapsed_seconds else 0.0, 3
        ),
        "error_rate": round(failures / len(samples), 4) if samples else 0.0,
        "status_codes": dict(Counter(str(sample.status_code) for sample in samples)),
    }


async def _timed(
    operation: Callable[[], Awaitable[httpx.Response]],
) -> Sample:
    started = time.perf_counter()
    response = await operation()
    return Sample(
        elapsed_ms=(time.perf_counter() - started) * 1000,
        status_code=response.status_code,
    )


async def _login(client: httpx.AsyncClient, actor_id: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": actor_id}
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['session_id']}"}


async def _create_conversation(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> str:
    response = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"channel": "widget", "order_id": "order_1001"},
    )
    response.raise_for_status()
    return response.json()["conversation_id"]


async def _run_serial(
    client: httpx.AsyncClient,
    customer_headers: dict[str, str],
    support_headers: dict[str, str],
    count: int,
) -> dict[str, dict[str, Any]]:
    operations: dict[str, list[Sample]] = {
        "authenticated_order_lookup": [],
        "conversation_creation": [],
        "order_investigation": [],
        "policy_retrieval": [],
        "staff_inbox": [],
        "handoff_transition": [],
    }

    for index in range(count):
        operations["authenticated_order_lookup"].append(
            await _timed(
                lambda: client.get(
                    "/api/v1/orders/order_1001", headers=customer_headers
                )
            )
        )
        started = time.perf_counter()
        conversation_response = await client.post(
            "/api/v1/conversations",
            headers=customer_headers,
            json={"channel": "widget", "order_id": "order_1001"},
        )
        operations["conversation_creation"].append(
            Sample(
                elapsed_ms=(time.perf_counter() - started) * 1000,
                status_code=conversation_response.status_code,
            )
        )
        conversation_response.raise_for_status()
        conversation_id = conversation_response.json()["conversation_id"]
        operations["order_investigation"].append(
            await _timed(
                lambda conversation_id=conversation_id: client.post(
                    f"/api/v1/conversations/{conversation_id}/messages",
                    headers=customer_headers,
                    json={"content": "Where is my delayed order?"},
                )
            )
        )

        policy_conversation_id = await _create_conversation(client, customer_headers)
        operations["policy_retrieval"].append(
            await _timed(
                lambda policy_conversation_id=policy_conversation_id: client.post(
                    f"/api/v1/conversations/{policy_conversation_id}/messages",
                    headers=customer_headers,
                    json={"content": "Are delivery dates guaranteed?"},
                )
            )
        )
        operations["staff_inbox"].append(
            await _timed(
                lambda: client.get("/api/v1/support/inbox", headers=support_headers)
            )
        )
        handoff_id = await _create_conversation(client, customer_headers)
        operations["handoff_transition"].append(
            await _timed(
                lambda handoff_id=handoff_id: client.post(
                    f"/api/v1/conversations/{handoff_id}/handoff",
                    headers=customer_headers,
                )
            )
        )

        if index == 0:
            # Keep the first iteration representative while explicitly proving
            # that customer ownership remains enforced in the same run.
            unauthorized = await client.get(
                "/api/v1/orders/order_1002", headers=customer_headers
            )
            if unauthorized.status_code != 404:
                raise RuntimeError(
                    f"customer ownership check returned {unauthorized.status_code}"
                )

    return {
        name: _summary(samples, sum(sample.elapsed_ms for sample in samples) / 1000)
        for name, samples in operations.items()
    }


async def _run_concurrent_order_lookup(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    requests: int,
    concurrency: int,
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one() -> Sample:
        async with semaphore:
            return await _timed(
                lambda: client.get("/api/v1/orders/order_1001", headers=headers)
            )

    started = time.perf_counter()
    samples = await asyncio.gather(*(one() for _ in range(requests)))
    return _summary(samples, time.perf_counter() - started)


async def _run_concurrent_handoff(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    concurrency: int,
) -> dict[str, Any]:
    conversation_id = await _create_conversation(client, headers)

    async def one() -> int:
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/handoff", headers=headers
        )
        return response.status_code

    statuses = await asyncio.gather(*(one() for _ in range(concurrency)))
    return {
        "requests": len(statuses),
        "status_codes": dict(Counter(str(status) for status in statuses)),
        "successful_takeovers": statuses.count(200),
        "expected_conflicts": statuses.count(409),
    }


async def _benchmark(count: int, concurrency: int) -> dict[str, Any]:
    app = create_app("sqlite+pysqlite:///:memory:")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        customer_headers = await _login(client, "customer_001")
        support_headers = await _login(client, "support_001")
        serial = await _run_serial(
            client, customer_headers, support_headers, count
        )
        concurrent_lookup = await _run_concurrent_order_lookup(
            client, customer_headers, requests=max(count * 2, concurrency), concurrency=concurrency
        )
        concurrent_handoff = await _run_concurrent_handoff(
            client, customer_headers, concurrency=concurrency
        )
    return {
        "database": "SQLite in-memory synthetic application",
        "serial_iterations": count,
        "concurrency": concurrency,
        "serial": serial,
        "concurrent_order_lookup": concurrent_lookup,
        "concurrent_handoff_guard": concurrent_handoff,
        "resource_observation": "CPU and RSS are not collected; no optional monitoring dependency is added.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    if args.iterations < 1 or args.concurrency < 1:
        parser.error("iterations and concurrency must be positive")
    print(json.dumps(asyncio.run(_benchmark(args.iterations, args.concurrency)), indent=2))


if __name__ == "__main__":
    main()
