"""Persist managed-policy index attempts and link embeddings to a version."""

from alembic import op
import sqlalchemy as sa


revision = "20261123_06"
down_revision = "20261123_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_index_jobs",
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("version_id", sa.String(length=128), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_role", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')",
            name="ck_policy_index_job_state",
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_policy_index_job_attempt"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["policy_versions.version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("version_id", "attempt", name="uq_policy_index_job_attempt"),
    )
    op.create_index("ix_policy_index_jobs_version_id", "policy_index_jobs", ["version_id"])
    op.create_index("ix_policy_index_jobs_state", "policy_index_jobs", ["state"])
    op.create_index(
        "ix_policy_index_jobs_idempotency_key",
        "policy_index_jobs",
        ["idempotency_key"],
    )

    # Existing corpus rows remain valid and unmanaged. Future managed index
    # updates set this nullable link to the durable policy version id.
    op.add_column(
        "policy_embeddings",
        sa.Column(
            "version_id",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_policy_embeddings_version_id",
        "policy_embeddings",
        ["version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_policy_embeddings_version_id",
        table_name="policy_embeddings",
    )
    op.drop_column("policy_embeddings", "version_id")
    op.drop_index("ix_policy_index_jobs_idempotency_key", table_name="policy_index_jobs")
    op.drop_index("ix_policy_index_jobs_state", table_name="policy_index_jobs")
    op.drop_index("ix_policy_index_jobs_version_id", table_name="policy_index_jobs")
    op.drop_table("policy_index_jobs")
