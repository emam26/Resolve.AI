"""Controlled grounded-answer behavior with no model or external service call."""

from typing import Sequence

from pydantic import BaseModel, ConfigDict

from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.models import PolicyAudience, PolicyEvidence, PolicyRecord
from backend.app.rag.retrieval import (
    is_sufficient_policy_match,
    retrieve_published_policy,
)


class GroundedAnswer(BaseModel):
    """The exact M2 answer shape, including explicit uncertainty state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str | None
    evidence: list[PolicyEvidence]
    grounded: bool
    needs_handoff: bool


def _answer_text(evidence: PolicyEvidence, corpus: Sequence[PolicyRecord]) -> str:
    """Use only a deterministic template attached to the cited policy record."""

    for record in corpus:
        if (
            record.document_id == evidence.document_id
            and record.document_version == evidence.document_version
            and record.section == evidence.section
            and record.release_id == evidence.release_id
        ):
            return record.answer_text or record.text
    # This path is defensive: evidence from the retriever should always come
    # from the same corpus. Returning citation text remains grounded if a
    # caller supplies an unusual but valid custom corpus.
    return evidence.text


def answer_from_published_policy(
    query: str,
    audience: PolicyAudience = "customer",
    *,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
    top_k: int = 3,
) -> GroundedAnswer:
    """Retrieve policy evidence and answer only when evidence is sufficient."""

    evidence = retrieve_published_policy(
        query, audience=audience, top_k=top_k, corpus=corpus
    )
    if not is_sufficient_policy_match(query, evidence):
        return GroundedAnswer(
            answer=None,
            evidence=[],
            grounded=False,
            needs_handoff=True,
        )

    return GroundedAnswer(
        answer=_answer_text(evidence[0], corpus),
        evidence=evidence,
        grounded=True,
        needs_handoff=False,
    )


__all__ = ["GroundedAnswer", "answer_from_published_policy"]
