"""Compatibility adapter for the legacy document/version route aliases.

The canonical M14 API is version-id based and is implemented by
``InMemoryResolveService``.  These aliases remain only for existing local
clients; they use the same repository and never widen authorization.
"""

from __future__ import annotations

from collections.abc import Iterable

from backend.app.contracts import ActorRole, ActorSummary
from backend.app.db.policies import (
    PolicyConflict,
    PolicyIndexUpdater,
    PolicyRepository,
    PolicySection,
    PolicyValidationError,
    StoredPolicyAudit,
    StoredPolicyVersion,
)


class PolicyManagementService:
    def __init__(self, *, repository: PolicyRepository) -> None:
        self.repository = repository

    @staticmethod
    def _require(actor: ActorSummary, allowed: set[str]) -> None:
        if actor.role not in allowed:
            raise PermissionError("policy management requires an authorized staff role")

    @staticmethod
    def _sections(sections: Iterable[object]) -> tuple[PolicySection, ...]:
        return tuple(
            item
            if isinstance(item, PolicySection)
            else PolicySection(item.section, item.text or item.content or "")
            for item in sections
        )

    def create_draft(self, actor: ActorSummary, **kwargs) -> StoredPolicyVersion:
        self._require(actor, {"support_agent", "merchant_admin"})
        return self.repository.create(
            actor_id=actor.actor_id,
            actor_role=actor.role,
            document_id=kwargs["document_id"],
            document_version=kwargs.get("document_version"),
            release_id=kwargs.get("release_id"),
            visibility=kwargs["visibility"],
            sections=self._sections(kwargs["sections"]),
            title=kwargs.get("title"),
        )

    def edit_draft(self, actor: ActorSummary, **kwargs) -> StoredPolicyVersion:
        self._require(actor, {"support_agent", "merchant_admin"})
        return self.repository.update_draft(
            kwargs["document_id"],
            kwargs["document_version"],
            actor_id=actor.actor_id,
            actor_role=actor.role,
            expected_revision=kwargs["expected_revision"],
            release_id=kwargs.get("release_id"),
            visibility=kwargs["visibility"],
            sections=self._sections(kwargs["sections"]),
            title=kwargs.get("title"),
        )

    def publish(self, actor: ActorSummary, **kwargs) -> StoredPolicyVersion:
        self._require(actor, {"merchant_admin"})
        return self.repository.publish(
            kwargs["document_id"],
            kwargs["document_version"],
            actor_id=actor.actor_id,
            actor_role=actor.role,
            expected_revision=kwargs["expected_revision"],
        )

    def index(self, actor: ActorSummary, **kwargs) -> StoredPolicyVersion:
        self._require(actor, {"merchant_admin"})
        record = self.repository.get(kwargs["document_id"], kwargs["document_version"])
        if record is None:
            raise KeyError(kwargs["document_version"])
        return self.repository.index(
            record.version_id,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            idempotency_key=kwargs.get("idempotency_key"),
        )

    def rollback(self, actor: ActorSummary, **kwargs) -> StoredPolicyVersion:
        self._require(actor, {"merchant_admin"})
        return self.repository.rollback(
            kwargs["document_id"],
            kwargs["document_version"],
            target_version=kwargs["target_version"],
            actor_id=actor.actor_id,
            actor_role=actor.role,
            expected_revision=kwargs["expected_revision"],
        )

    def audit(self, actor: ActorSummary, **kwargs) -> list[StoredPolicyAudit]:
        self._require(actor, {"merchant_admin"})
        return self.repository.audits(
            document_id=kwargs["document_id"],
            document_version=kwargs["document_version"],
        )


__all__ = [
    "PolicyConflict",
    "PolicyIndexUpdater",
    "PolicyManagementService",
    "PolicySection",
    "PolicyValidationError",
]
