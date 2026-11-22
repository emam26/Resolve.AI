"""Small, privacy-conscious diagnostics shared by the HTTP and workflow layers."""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from typing import Final
from uuid import UUID, uuid4


LOGGER = logging.getLogger("resolveai")
_EVENT_FIELDS: Final = {
    "investigation_completed": frozenset(
        {
            "outcome",
            "retrieval_mode",
            "evidence_count",
            "handed_off",
            "handoff_reason",
            "elapsed_ms",
        }
    ),
    "investigation_failed": frozenset(
        {"error_category", "error_type", "elapsed_ms"}
    ),
    "policy_retrieval_fallback": frozenset(
        {"retrieval_mode", "error_category", "error_type"}
    ),
}
_RETRIEVAL_MODES: Final = frozenset(
    {"not_applicable", "lexical", "semantic", "lexical_fallback"}
)
_HANDOFF_REASONS: Final = frozenset(
    {
        "conversation_not_ai_active",
        "empty_query",
        "insufficient_published_policy",
        "missing_order_id",
        "missing_workflow_result",
        "order_facts_unavailable",
        "refund_requires_human_review",
        "unsupported_investigation_intent",
        "workflow_error",
    }
)
_ERROR_CATEGORIES: Final = frozenset(
    {"semantic_backend_unavailable", "workflow_exception"}
)
_ERROR_TYPE_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")
_CORRELATION_ID: ContextVar[str | None] = ContextVar(
    "resolveai_correlation_id", default=None
)


def new_correlation_id(candidate: str | None = None) -> str:
    """Return a normalized UUID, accepting only valid incoming IDs."""

    if candidate:
        try:
            return str(UUID(candidate))
        except ValueError:
            pass
    return str(uuid4())


def set_correlation_id(value: str):
    """Set the request-local ID and return its context token."""

    return _CORRELATION_ID.set(value)


def reset_correlation_id(token) -> None:
    """Restore the previous request-local ID."""

    _CORRELATION_ID.reset(token)


def current_correlation_id() -> str | None:
    return _CORRELATION_ID.get()


def log_event(event: str, **fields: object) -> None:
    """Emit one allowlisted JSON event without accepting raw customer content."""

    allowed_fields = _EVENT_FIELDS.get(event)
    if allowed_fields is None:
        raise ValueError(f"unsupported diagnostics event: {event}")
    unexpected_fields = set(fields).difference(allowed_fields)
    if unexpected_fields:
        raise ValueError(
            "diagnostic fields are not allowlisted: "
            + ", ".join(sorted(unexpected_fields))
        )
    for name, value in fields.items():
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise TypeError(f"diagnostic field {name} must be JSON scalar")
        if name == "retrieval_mode" and value not in _RETRIEVAL_MODES:
            raise ValueError(f"unsupported retrieval mode: {value}")
        if name == "outcome" and value not in {"ANSWER", "HANDOFF"}:
            raise ValueError(f"unsupported investigation outcome: {value}")
        if (
            name == "handoff_reason"
            and value is not None
            and value not in _HANDOFF_REASONS
        ):
            raise ValueError(f"unsupported handoff reason: {value}")
        if name == "error_category" and value not in _ERROR_CATEGORIES:
            raise ValueError(f"unsupported diagnostic error category: {value}")
        if name == "error_type" and (
            not isinstance(value, str) or not _ERROR_TYPE_PATTERN.fullmatch(value)
        ):
            raise ValueError("diagnostic error type is not a safe category")
        if name in {"evidence_count", "elapsed_ms"} and (
            not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
        ):
            raise ValueError(f"diagnostic field {name} must be non-negative")

    payload: dict[str, object] = {"event": event}
    correlation_id = current_correlation_id()
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id
    payload.update(fields)
    LOGGER.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))


__all__ = [
    "current_correlation_id",
    "log_event",
    "new_correlation_id",
    "reset_correlation_id",
    "set_correlation_id",
]
