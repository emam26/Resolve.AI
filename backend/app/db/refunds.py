"""SQLAlchemy persistence for simulated refund review records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import uuid4

from sqlalchemy import Integer, String, UniqueConstraint, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from .conversations import Base, ConversationRow, create_database_engine


DEFAULT_REFUND_DATABASE_URL: Final = "sqlite+pysqlite:///:memory:"


class RefundRow(Base):
    __tablename__ = "refund_reviews"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_refund_conversation_idempotency",
        ),
    )

    refund_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String, nullable=True)


@dataclass(frozen=True)
class StoredRefund:
    refund_id: str
    conversation_id: str
    order_id: str
    amount_cents: int
    reason: str
    idempotency_key: str
    state: str
    requested_by: str
    decided_by: str | None
    decision_note: str | None


class RefundRepository:
    """Persist review records without any payment-provider behavior."""

    def __init__(
        self, database_url: str = DEFAULT_REFUND_DATABASE_URL, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)

    def get(self, refund_id: str) -> StoredRefund | None:
        with self._session_factory() as session:
            row = session.get(RefundRow, refund_id)
            return None if row is None else self._stored(row)

    def get_by_idempotency(
        self, conversation_id: str, idempotency_key: str
    ) -> StoredRefund | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(RefundRow).where(
                    RefundRow.conversation_id == conversation_id,
                    RefundRow.idempotency_key == idempotency_key,
                )
            )
            return None if row is None else self._stored(row)

    def create(
        self,
        *,
        conversation_id: str,
        order_id: str,
        amount_cents: int,
        reason: str,
        idempotency_key: str,
        requested_by: str,
    ) -> StoredRefund | None:
        row = RefundRow(
            refund_id=f"refund_{uuid4().hex}",
            conversation_id=conversation_id,
            order_id=order_id,
            amount_cents=amount_cents,
            reason=reason,
            idempotency_key=idempotency_key,
            state="PENDING_REVIEW",
            requested_by=requested_by,
            decided_by=None,
            decision_note=None,
        )
        try:
            with self._session_factory.begin() as session:
                conversation = session.scalar(
                    select(ConversationRow)
                    .where(ConversationRow.conversation_id == conversation_id)
                    .with_for_update()
                )
                if conversation is None or conversation.state != "HUMAN_ACTIVE":
                    return None
                session.add(row)
        except IntegrityError:
            existing = self.get_by_idempotency(conversation_id, idempotency_key)
            if existing is None:
                raise
            return existing
        return self._stored(row)

    def list_all(self) -> list[StoredRefund]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(RefundRow).order_by(RefundRow.refund_id)
            ).all()
            return [self._stored(row) for row in rows]

    def decide(
        self,
        refund_id: str,
        *,
        expected_state: str,
        new_state: str,
        decided_by: str,
        decision_note: str,
    ) -> StoredRefund | None:
        with self._session_factory.begin() as session:
            result = session.execute(
                update(RefundRow)
                .where(
                    RefundRow.refund_id == refund_id,
                    RefundRow.state == expected_state,
                )
                .values(
                    state=new_state,
                    decided_by=decided_by,
                    decision_note=decision_note,
                )
            )
            if result.rowcount != 1:
                return None
        return self.get(refund_id)

    @staticmethod
    def _stored(row: RefundRow) -> StoredRefund:
        return StoredRefund(
            refund_id=row.refund_id,
            conversation_id=row.conversation_id,
            order_id=row.order_id,
            amount_cents=row.amount_cents,
            reason=row.reason,
            idempotency_key=row.idempotency_key,
            state=row.state,
            requested_by=row.requested_by,
            decided_by=row.decided_by,
            decision_note=row.decision_note,
        )
