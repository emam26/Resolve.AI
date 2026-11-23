"""Small response models for read-only staff workspace surfaces."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.contracts import ActorSummary


class StaffModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecentActivity(StaffModel):
    conversation_id: str
    state: str
    order_id: str | None
    customer_id: str
    assigned_staff_id: str | None
    activity_type: str
    last_activity_at: datetime | None


class OperationsSummaryResponse(StaffModel):
    total_conversations: int
    active_conversations: int
    waiting_conversations: int
    resolved_conversations: int
    pending_refund_reviews: int
    recent_activity: list[RecentActivity]


class PolicySectionResponse(StaffModel):
    document_id: str
    document_version: str
    section: str
    release_id: str
    status: str
    visibility: str
    text: str
    # Managed policy metadata is additive; legacy corpus rows leave these at
    # their defaults so existing read-only clients retain their shape.
    version_id: str | None = None
    title: str | None = None
    state: str | None = None
    revision: int | None = None
    is_active: bool | None = None
    failure_reason: str | None = None
    updated_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class PolicyListResponse(StaffModel):
    policies: list[PolicySectionResponse]


class PolicyDocumentResponse(StaffModel):
    document_id: str
    policies: list[PolicySectionResponse]


class PolicySectionInput(StaffModel):
    section: str = ""
    text: str | None = None
    content: str | None = None


class CreatePolicyRequest(StaffModel):
    document_id: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    document_version: str | None = Field(default=None, min_length=1, max_length=64)
    release_id: str | None = Field(default=None, min_length=1, max_length=128)
    visibility: Literal["public", "internal"]
    sections: list[PolicySectionInput] = Field(min_length=1, max_length=200)


class EditPolicyRequest(StaffModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    release_id: str | None = Field(default=None, min_length=1, max_length=128)
    visibility: Literal["public", "internal"] | None = None
    sections: list[PolicySectionInput] | None = Field(default=None, max_length=200)


class RollbackPolicyRequest(StaffModel):
    document_version: str | None = Field(default=None, min_length=1, max_length=64)
    target_version: str | None = Field(default=None, min_length=1, max_length=64)
    expected_revision: int | None = Field(default=None, ge=1)


class PolicyVersionResponse(StaffModel):
    version_id: str
    document_id: str
    title: str
    document_version: str
    release_id: str
    state: str
    status: str
    visibility: str
    revision: int
    is_active: bool
    failure_reason: str | None
    index_state: str | None = None
    created_at: datetime
    updated_at: datetime
    effective_from: datetime | None
    effective_to: datetime | None
    sections: list[PolicySectionInput]


class PolicyVersionsResponse(StaffModel):
    versions: list[PolicyVersionResponse]


class PolicyValidationResponse(StaffModel):
    valid: bool
    errors: list[str]
    state: str
    revision: int


class PolicyAuditResponse(StaffModel):
    audit_id: str
    actor_id: str
    actor_role: str | None = None
    action: str
    document_id: str
    document_version: str
    release_id: str
    from_state: str | None
    to_state: str | None
    metadata: dict[str, object]
    revision: int | None = None
    created_at: datetime


class PolicyAuditListResponse(StaffModel):
    events: list[PolicyAuditResponse]


class WorkspaceTeamResponse(StaffModel):
    team: list[ActorSummary]


class WorkspaceSettingsResponse(StaffModel):
    merchant_name: str
    policy_source: str
    policy_retrieval_mode: str
    response_generation_mode: str
    database_ready: bool
    commerce_database_configured: bool
