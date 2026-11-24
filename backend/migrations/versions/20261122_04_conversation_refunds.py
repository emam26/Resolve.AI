"""Own conversation and refund persistence in the Alembic schema."""

from alembic import op
from alembic import context
import sqlalchemy as sa


revision = "20261122_04"
down_revision = "20261122_03"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _ensure_check(table: str, name: str, expression: str) -> None:
    if context.is_offline_mode():
        op.create_check_constraint(name, table, expression)
        return
    checks = {item.get("name") for item in _inspector().get_check_constraints(table)}
    if name not in checks:
        op.create_check_constraint(name, table, expression)


def _ensure_foreign_key(
    table: str,
    name: str,
    columns: list[str],
    referent_table: str,
    referent_columns: list[str],
) -> None:
    if context.is_offline_mode():
        op.create_foreign_key(
            name,
            table,
            referent_table,
            columns,
            referent_columns,
            ondelete="CASCADE",
        )
        return
    keys = {item.get("name") for item in _inspector().get_foreign_keys(table)}
    if name not in keys:
        op.create_foreign_key(
            name,
            table,
            referent_table,
            columns,
            referent_columns,
            ondelete="CASCADE",
        )


def _ensure_unique(table: str, name: str, columns: list[str]) -> None:
    if context.is_offline_mode():
        op.create_unique_constraint(name, table, columns)
        return
    uniques = {item.get("name") for item in _inspector().get_unique_constraints(table)}
    if name not in uniques:
        op.create_unique_constraint(name, table, columns)


def _ensure_index(table: str, name: str, columns: list[str]) -> None:
    if context.is_offline_mode():
        op.create_index(name, table, columns)
        return
    indexes = {item.get("name") for item in _inspector().get_indexes(table)}
    if name not in indexes:
        op.create_index(name, table, columns)


def upgrade() -> None:
    # Alembic's offline MockConnection has no inspection system.  Treat the
    # offline path as a fresh schema and let the operation stream render the
    # complete migration SQL; online upgrades retain the idempotent inspection
    # behavior used for existing databases.
    tables = set() if context.is_offline_mode() else set(_inspector().get_table_names())

    if "conversations" not in tables:
        op.create_table(
            "conversations",
            sa.Column("conversation_id", sa.String(length=128), nullable=False),
            sa.Column("owner_customer_id", sa.String(length=128), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("order_id", sa.String(length=128), nullable=True),
            sa.Column("assigned_staff_id", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "state IN ('AI_ACTIVE', 'HANDOFF_QUEUED', 'HUMAN_ACTIVE', 'RESOLVED')",
                name="ck_conversations_state",
            ),
            sa.CheckConstraint("channel = 'widget'", name="ck_conversations_channel"),
            sa.PrimaryKeyConstraint("conversation_id"),
        )
    else:
        _ensure_check(
            "conversations",
            "ck_conversations_state",
            "state IN ('AI_ACTIVE', 'HANDOFF_QUEUED', 'HUMAN_ACTIVE', 'RESOLVED')",
        )
        _ensure_check("conversations", "ck_conversations_channel", "channel = 'widget'")

    _ensure_index(
        "conversations",
        "ix_conversations_owner_customer_id",
        ["owner_customer_id"],
    )
    _ensure_index("conversations", "ix_conversations_state", ["state"])
    _ensure_index(
        "conversations",
        "ix_conversations_assigned_staff_id",
        ["assigned_staff_id"],
    )

    if "conversation_messages" not in tables:
        op.create_table(
            "conversation_messages",
            sa.Column("message_id", sa.String(length=128), nullable=False),
            sa.Column("conversation_id", sa.String(length=128), nullable=False),
            sa.Column("sequence_number", sa.Integer(), nullable=False),
            sa.Column("author_type", sa.String(length=32), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "author_type IN ('customer', 'assistant', 'staff')",
                name="ck_conversation_message_author_type",
            ),
            sa.ForeignKeyConstraint(
                ["conversation_id"],
                ["conversations.conversation_id"],
                name="fk_conversation_messages_conversation",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("message_id"),
            sa.UniqueConstraint(
                "conversation_id",
                "sequence_number",
                name="uq_conversation_message_sequence",
            ),
        )
    else:
        _ensure_check(
            "conversation_messages",
            "ck_conversation_message_author_type",
            "author_type IN ('customer', 'assistant', 'staff')",
        )
        _ensure_foreign_key(
            "conversation_messages",
            "fk_conversation_messages_conversation",
            ["conversation_id"],
            "conversations",
            ["conversation_id"],
        )
        _ensure_unique(
            "conversation_messages",
            "uq_conversation_message_sequence",
            ["conversation_id", "sequence_number"],
        )

    _ensure_index(
        "conversation_messages",
        "ix_conversation_messages_conversation_id",
        ["conversation_id"],
    )
    _ensure_index(
        "conversation_messages",
        "ix_conversation_messages_sequence_number",
        ["sequence_number"],
    )

    if "resolveai_id_sequences" not in tables:
        op.create_table(
            "resolveai_id_sequences",
            sa.Column("sequence_key", sa.String(length=32), nullable=False),
            sa.Column("next_value", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("sequence_key"),
        )

    sequence_sql = sa.text(
        "INSERT INTO resolveai_id_sequences (sequence_key, next_value) "
        "VALUES ('conversation', 1001), ('message', 1001) "
        "ON CONFLICT (sequence_key) DO NOTHING"
    )
    if context.is_offline_mode():
        op.execute(sequence_sql)
    else:
        op.get_bind().execute(sequence_sql)

    if "refund_reviews" not in tables:
        op.create_table(
            "refund_reviews",
            sa.Column("refund_id", sa.String(length=128), nullable=False),
            sa.Column("conversation_id", sa.String(length=128), nullable=False),
            sa.Column("order_id", sa.String(length=128), nullable=False),
            sa.Column("amount_cents", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=256), nullable=False),
            sa.Column("state", sa.String(length=64), nullable=False),
            sa.Column("requested_by", sa.String(length=128), nullable=False),
            sa.Column("decided_by", sa.String(length=128), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "state IN ('PENDING_REVIEW', 'APPROVED_EXTERNAL_ACTION_REQUIRED', 'REJECTED')",
                name="ck_refund_reviews_state",
            ),
            sa.ForeignKeyConstraint(
                ["conversation_id"],
                ["conversations.conversation_id"],
                name="fk_refund_reviews_conversation",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("refund_id"),
            sa.UniqueConstraint(
                "conversation_id",
                "idempotency_key",
                name="uq_refund_conversation_idempotency",
            ),
        )
    else:
        _ensure_check(
            "refund_reviews",
            "ck_refund_reviews_state",
            "state IN ('PENDING_REVIEW', 'APPROVED_EXTERNAL_ACTION_REQUIRED', 'REJECTED')",
        )
        _ensure_foreign_key(
            "refund_reviews",
            "fk_refund_reviews_conversation",
            ["conversation_id"],
            "conversations",
            ["conversation_id"],
        )
        _ensure_unique(
            "refund_reviews",
            "uq_refund_conversation_idempotency",
            ["conversation_id", "idempotency_key"],
        )

    _ensure_index("refund_reviews", "ix_refund_reviews_conversation_id", ["conversation_id"])
    _ensure_index("refund_reviews", "ix_refund_reviews_order_id", ["order_id"])
    _ensure_index("refund_reviews", "ix_refund_reviews_state", ["state"])


def downgrade() -> None:
    op.drop_table("refund_reviews")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    op.drop_table("resolveai_id_sequences")
