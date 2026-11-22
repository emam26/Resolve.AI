"""SQLite-friendly conversation persistence for the local V1 workflows.

The repository deliberately uses SQLAlchemy rather than embedding storage logic
in the FastAPI routes.  It accepts any SQLAlchemy URL, so the same model can be
pointed at PostgreSQL later, while the current tests remain deterministic and
offline with SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from sqlalchemy import DateTime, Integer, String, create_engine, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


DEFAULT_DATABASE_URL: Final = "sqlite+pysqlite:///:memory:"
_UNSET = object()


class Base(DeclarativeBase):
    pass


class ConversationRow(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_customer_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assigned_staff_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageRow(Base):
    __tablename__ = "conversation_messages"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    author_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class StoredMessage:
    message_id: str
    author_type: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class StoredConversation:
    conversation_id: str
    owner_customer_id: str
    channel: str
    state: str
    order_id: str | None
    assigned_staff_id: str | None
    messages: tuple[StoredMessage, ...]


class IdSequenceRow(Base):
    """Database-locked allocator preserving readable demo identifiers."""

    __tablename__ = "resolveai_id_sequences"

    sequence_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False)


def create_database_engine(database_url: str) -> Engine:
    """Create the shared local engine used by conversation and refund stores."""

    engine_kwargs: dict[str, object] = {"future": True}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            engine_kwargs["poolclass"] = StaticPool
    return create_engine(database_url, **engine_kwargs)


def _utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC value for SQLite and PostgreSQL rows."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ConversationRepository:
    """Persist conversations and messages behind a small testable interface."""

    def __init__(
        self, database_url: str = DEFAULT_DATABASE_URL, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        self._initialize_sequences()

    def _initialize_sequences(self) -> None:
        with self._session_factory.begin() as session:
            if session.get(IdSequenceRow, "conversation") is None:
                values = session.scalars(select(ConversationRow.conversation_id)).all()
                numbers = [
                    int(value.removeprefix("conv_"))
                    for value in values
                    if value.startswith("conv_")
                    and value.removeprefix("conv_").isdigit()
                ]
                session.add(
                    IdSequenceRow(
                        sequence_key="conversation",
                        next_value=max(numbers, default=1000) + 1,
                    )
                )
            if session.get(IdSequenceRow, "message") is None:
                session.add(IdSequenceRow(sequence_key="message", next_value=1001))

    def ensure_conversation(
        self,
        conversation_id: str,
        *,
        owner_customer_id: str,
        channel: str,
        state: str,
        order_id: str | None,
        created_at: datetime,
    ) -> StoredConversation:
        with self._session_factory.begin() as session:
            row = session.get(ConversationRow, conversation_id)
            if row is None:
                session.add(
                    ConversationRow(
                        conversation_id=conversation_id,
                        owner_customer_id=owner_customer_id,
                        channel=channel,
                        state=state,
                        order_id=order_id,
                        assigned_staff_id=None,
                        created_at=_utc(created_at),
                    )
                )
        return self.get(conversation_id)  # type: ignore[return-value]

    def create_conversation(
        self,
        *,
        owner_customer_id: str,
        channel: str,
        state: str,
        order_id: str | None,
        created_at: datetime,
    ) -> StoredConversation:
        with self._session_factory.begin() as session:
            conversation_id = f"conv_{self._allocate_number(session, 'conversation')}"
            session.add(
                ConversationRow(
                    conversation_id=conversation_id,
                    owner_customer_id=owner_customer_id,
                    channel=channel,
                    state=state,
                    order_id=order_id,
                    assigned_staff_id=None,
                    created_at=_utc(created_at),
                )
            )
        return self.get(conversation_id)  # type: ignore[return-value]

    def get(self, conversation_id: str) -> StoredConversation | None:
        with self._session_factory() as session:
            row = session.get(ConversationRow, conversation_id)
            if row is None:
                return None
            messages = session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.sequence_number)
            ).all()
            return StoredConversation(
                conversation_id=row.conversation_id,
                owner_customer_id=row.owner_customer_id,
                channel=row.channel,
                state=row.state,
                order_id=row.order_id,
                assigned_staff_id=row.assigned_staff_id,
                messages=tuple(
                    StoredMessage(
                        message_id=message.message_id,
                        author_type=message.author_type,
                        content=message.content,
                        created_at=_utc(message.created_at),
                    )
                    for message in messages
                ),
            )

    def append_message(
        self,
        conversation_id: str,
        *,
        author_type: str,
        content: str,
        created_at: datetime,
    ) -> StoredConversation | None:
        with self._session_factory.begin() as session:
            conversation = session.get(ConversationRow, conversation_id)
            if conversation is None:
                return None
            message_number = self._allocate_number(session, "message")
            session.add(
                MessageRow(
                    message_id=f"msg_{message_number}",
                    conversation_id=conversation_id,
                    sequence_number=message_number,
                    author_type=author_type,
                    content=content,
                    created_at=_utc(created_at),
                )
            )
        return self.get(conversation_id)

    def append_message_if_state(
        self,
        conversation_id: str,
        *,
        expected_state: str,
        author_type: str,
        content: str,
        created_at: datetime,
    ) -> StoredConversation | None:
        """Append only while the conversation remains in the expected state."""

        with self._session_factory.begin() as session:
            # The conditional update acquires the row lock on PostgreSQL and
            # makes the state check and subsequent insert one transaction.
            state_guard = session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.conversation_id == conversation_id,
                    ConversationRow.state == expected_state,
                )
                .values(state=expected_state)
            )
            if state_guard.rowcount != 1:
                return None
            message_number = self._allocate_number(session, "message")
            session.add(
                MessageRow(
                    message_id=f"msg_{message_number}",
                    conversation_id=conversation_id,
                    sequence_number=message_number,
                    author_type=author_type,
                    content=content,
                    created_at=_utc(created_at),
                )
            )
        return self.get(conversation_id)

    def transition(
        self,
        conversation_id: str,
        *,
        expected_state: str,
        new_state: str,
        assigned_staff_id: str | None | object = _UNSET,
    ) -> StoredConversation | None:
        values: dict[str, object] = {"state": new_state}
        if assigned_staff_id is not _UNSET:
            values["assigned_staff_id"] = assigned_staff_id
        with self._session_factory.begin() as session:
            result = session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.conversation_id == conversation_id,
                    ConversationRow.state == expected_state,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                return None
        return self.get(conversation_id)

    def list_support(self) -> list[StoredConversation]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ConversationRow)
                .where(ConversationRow.state.in_(("HANDOFF_QUEUED", "HUMAN_ACTIVE")))
                .order_by(ConversationRow.created_at, ConversationRow.conversation_id)
            ).all()
            return [self._snapshot(session, row) for row in rows]

    @staticmethod
    def _allocate_number(session, sequence_key: str) -> int:
        sequence = session.scalar(
            select(IdSequenceRow)
            .where(IdSequenceRow.sequence_key == sequence_key)
            .with_for_update()
        )
        if sequence is None:
            raise RuntimeError(f"missing ID sequence: {sequence_key}")
        value = sequence.next_value
        sequence.next_value += 1
        return value

    @staticmethod
    def _snapshot(session, row: ConversationRow) -> StoredConversation:
        messages = session.scalars(
            select(MessageRow)
            .where(MessageRow.conversation_id == row.conversation_id)
            .order_by(MessageRow.sequence_number)
        ).all()
        return StoredConversation(
            conversation_id=row.conversation_id,
            owner_customer_id=row.owner_customer_id,
            channel=row.channel,
            state=row.state,
            order_id=row.order_id,
            assigned_staff_id=row.assigned_staff_id,
            messages=tuple(
                StoredMessage(
                    message_id=message.message_id,
                    author_type=message.author_type,
                    content=message.content,
                    created_at=_utc(message.created_at),
                )
                for message in messages
            ),
        )
