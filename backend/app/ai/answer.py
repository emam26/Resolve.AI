"""Controlled grounded-answer behavior with no model or external service call."""

from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict, PrivateAttr

from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.models import PolicyAudience, PolicyEvidence, PolicyRecord
from backend.app.rag.retrieval import (
    is_sufficient_policy_match,
    retrieve_published_policy,
)
from backend.app.rag.semantic import is_sufficient_semantic_match


class GroundedAnswer(BaseModel):
    """The exact M2 answer shape, including explicit uncertainty state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str | None
    evidence: list[PolicyEvidence]
    grounded: bool
    needs_handoff: bool
    _retrieval_mode: str = PrivateAttr(default="lexical")

    @property
    def retrieval_mode(self) -> str:
        """Internal execution mode; excluded from the frozen M2 JSON shape."""

        return self._retrieval_mode


class PolicyRetriever(Protocol):
    """Injected retrieval boundary for published, audience-visible evidence.

    Implementations must apply publication status and audience visibility
    filtering before returning evidence.  A semantic implementation may use
    pgvector or an offline deterministic equivalent; the answer layer does not
    know which storage backend produced the evidence.
    """

    def retrieve_published_policy(
        self,
        query: str,
        audience: PolicyAudience = "customer",
        top_k: int = 3,
    ) -> Sequence[PolicyEvidence]:
        """Return only published evidence visible to the requested audience."""


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


def _audience_allows_evidence(
    evidence: PolicyEvidence,
    audience: PolicyAudience,
) -> bool:
    """Keep the customer boundary closed if an injected retriever misbehaves.

    Publication status is authoritative in the retriever/index contract: both
    the in-memory and PostgreSQL implementations filter it before producing
    ``PolicyEvidence``.  Evidence deliberately retains the frozen M2 shape,
    so the answer layer can defensively enforce visibility without discarding
    published PostgreSQL versions that are not in the small local corpus.
    """

    if evidence.status != "published":
        return False
    return audience != "customer" or evidence.visibility == "public"


def answer_from_published_policy(
    query: str,
    audience: PolicyAudience = "customer",
    *,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
    top_k: int = 3,
    policy_retriever: PolicyRetriever | None = None,
) -> GroundedAnswer:
    """Retrieve policy evidence and answer only when evidence is sufficient."""

    if policy_retriever is None:
        evidence = retrieve_published_policy(
            query, audience=audience, top_k=top_k, corpus=corpus
        )
        sufficient = is_sufficient_policy_match(query, evidence)
        retrieval_mode = "lexical"
    else:
        try:
            evidence = [
                item
                for item in policy_retriever.retrieve_published_policy(
                    query, audience=audience, top_k=top_k
                )
                if _audience_allows_evidence(item, audience)
            ]
            sufficient = is_sufficient_semantic_match(evidence)
            retrieval_mode = "semantic"
        except Exception:
            # A failed semantic backend must degrade to the deterministic
            # lexical baseline, never to an unsupported confident answer.
            evidence = retrieve_published_policy(
                query, audience=audience, top_k=top_k, corpus=corpus
            )
            sufficient = is_sufficient_policy_match(query, evidence)
            retrieval_mode = "lexical_fallback"

    if not sufficient:
        response = GroundedAnswer(
            answer=None,
            evidence=[],
            grounded=False,
            needs_handoff=True,
        )
        response._retrieval_mode = retrieval_mode
        return response

    response = GroundedAnswer(
        answer=_answer_text(evidence[0], corpus),
        evidence=evidence,
        grounded=True,
        needs_handoff=False,
    )
    response._retrieval_mode = retrieval_mode
    return response


__all__ = ["GroundedAnswer", "PolicyRetriever", "answer_from_published_policy"]
