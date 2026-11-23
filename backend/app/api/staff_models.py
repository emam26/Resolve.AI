"""Small response models for read-only staff workspace surfaces."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

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


class PolicyListResponse(StaffModel):
    policies: list[PolicySectionResponse]


class PolicyDocumentResponse(StaffModel):
    document_id: str
    policies: list[PolicySectionResponse]


class WorkspaceTeamResponse(StaffModel):
    team: list[ActorSummary]


class WorkspaceSettingsResponse(StaffModel):
    merchant_name: str
    policy_source: str
    policy_retrieval_mode: str
    response_generation_mode: str
    database_ready: bool
    commerce_database_configured: bool
