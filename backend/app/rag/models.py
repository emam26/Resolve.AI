"""Typed, transport-independent policy records and citation objects."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PolicyAudience = Literal[
    "customer",
    "support_agent",
    "refund_approver",
    "merchant_admin",
]
PolicyStatus = Literal["draft", "unpublished", "published"]
PolicyVisibility = Literal["public", "internal"]


class PolicyModel(BaseModel):
    """Policy models are immutable and reject accidental schema expansion."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyRecord(PolicyModel):
    """A synthetic policy section that can be indexed by the offline retriever."""

    document_id: str
    document_version: str
    section: str
    release_id: str
    status: PolicyStatus
    visibility: PolicyVisibility
    text: str
    # This is an answer template owned by the deterministic service, not part
    # of a customer evidence object.
    answer_text: str | None = None


class PolicyEvidence(PolicyModel):
    """The exact evidence shape frozen by the M2 contract.

    ``status`` is an internal guard and is excluded from transport JSON. It
    lets the answer boundary re-check publication even when a retriever is
    injected, without changing the public citation shape.
    """

    document_id: str
    document_version: str
    section: str
    release_id: str
    visibility: PolicyVisibility
    score: float
    text: str
    status: PolicyStatus = Field(default="published", exclude=True)


# A citation is intentionally the same transport shape as evidence in M2.
PolicyCitation = PolicyEvidence
