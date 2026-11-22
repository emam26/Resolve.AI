"""Deterministic lexical retrieval over published policy sections."""

import re
from typing import Iterable, Sequence

from .corpus import POLICY_CORPUS
from .models import PolicyAudience, PolicyEvidence, PolicyRecord


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "can",
        "do",
        "does",
        "for",
        "how",
        "i",
        "if",
        "in",
        "is",
        "me",
        "my",
        "of",
        "on",
        "please",
        "the",
        "to",
        "what",
        "when",
        "where",
        "why",
        "with",
        "you",
        "your",
    }
)
_STAFF_AUDIENCES = frozenset(
    {"support_agent", "refund_approver", "merchant_admin"}
)
_VALID_AUDIENCES = frozenset({"customer", *_STAFF_AUDIENCES})


def _normalise_token(token: str) -> str:
    """Apply only small, deterministic morphology for singular/plural queries."""

    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def _tokens(value: str) -> set[str]:
    return {
        _normalise_token(token)
        for token in _TOKEN_PATTERN.findall(value.lower())
        if token not in _STOP_WORDS
    }


def _audience_allows(record: PolicyRecord, audience: str) -> bool:
    if record.status != "published":
        return False
    if audience == "customer":
        return record.visibility == "public"
    return record.visibility in {"public", "internal"}


def _evidence(record: PolicyRecord, score: float) -> PolicyEvidence:
    return PolicyEvidence(
        document_id=record.document_id,
        document_version=record.document_version,
        section=record.section,
        release_id=record.release_id,
        visibility=record.visibility,
        score=score,
        text=record.text,
        status=record.status,
    )


def retrieve_published_policy(
    query: str,
    audience: PolicyAudience = "customer",
    top_k: int = 3,
    *,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
) -> list[PolicyEvidence]:
    """Retrieve visible, published policy sections using stable lexical scores.

    Scores are the number of distinct normalized query terms present in the
    section. Ties are resolved by stable policy identifiers, so repeated runs
    and offline tests have identical output.
    """

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if audience not in _VALID_AUDIENCES:
        raise ValueError(f"unsupported audience: {audience}")

    query_terms = _tokens(query)
    if not query_terms:
        return []

    ranked: list[tuple[float, PolicyRecord]] = []
    for record in corpus:
        if not _audience_allows(record, audience):
            continue
        record_terms = _tokens(f"{record.section} {record.text}")
        score = float(len(query_terms & record_terms))
        if score > 0:
            ranked.append((score, record))

    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1].document_id,
            item[1].document_version,
            item[1].section,
            item[1].release_id,
        )
    )
    return [_evidence(record, score) for score, record in ranked[:top_k]]


def is_sufficient_policy_match(
    query: str,
    evidence: Sequence[PolicyEvidence],
    *,
    minimum_score: float = 2.0,
    minimum_query_coverage: float = 0.75,
) -> bool:
    """Reject weak lexical overlap before it can support a grounded answer."""

    query_terms = _tokens(query)
    if not query_terms or not evidence:
        return False
    if evidence[0].score < minimum_score:
        return False
    return evidence[0].score / len(query_terms) >= minimum_query_coverage


__all__ = ["is_sufficient_policy_match", "retrieve_published_policy"]
