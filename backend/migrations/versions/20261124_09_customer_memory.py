"""Add bounded, customer-scoped memory records."""

from alembic import op
import sqlalchemy as sa


revision = "20261124_09"
down_revision = "20261124_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_memories",
        sa.Column("memory_id", sa.String(length=128), nullable=False),
        sa.Column("customer_id", sa.String(length=128), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(length=512), nullable=False),
        sa.Column("provenance", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("memory_id"),
        sa.UniqueConstraint(
            "customer_id", "slot", name="uq_customer_memory_customer_slot"
        ),
        sa.CheckConstraint("customer_id <> ''", name="ck_customer_memory_customer_id"),
        sa.CheckConstraint("slot >= 0", name="ck_customer_memory_slot"),
        sa.CheckConstraint(
            "length(content) BETWEEN 1 AND 512",
            name="ck_customer_memory_content_length",
        ),
        sa.CheckConstraint(
            "length(provenance) BETWEEN 1 AND 64",
            name="ck_customer_memory_provenance_length",
        ),
    )
    op.create_index("ix_customer_memories_customer_id", "customer_memories", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_memories_customer_id", table_name="customer_memories")
    op.drop_table("customer_memories")
