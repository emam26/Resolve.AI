"""Add persistent policy lifecycle, index-state and audit tables."""

from alembic import op
import sqlalchemy as sa


revision = "20261123_05"
down_revision = "20261122_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_documents",
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_table(
        "policy_versions",
        sa.Column("version_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("document_version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("index_state", sa.String(length=32), nullable=False, server_default="NOT_INDEXED"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "state IN ('DRAFT', 'INDEXING', 'READY_FOR_TEST', 'PUBLISHED', 'UNPUBLISHED', 'FAILED')",
            name="ck_policy_versions_state",
        ),
        sa.CheckConstraint(
            "index_state IN ('NOT_INDEXED', 'READY', 'UNAVAILABLE', 'FAILED')",
            name="ck_policy_versions_index_state",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'internal')",
            name="ck_policy_versions_visibility",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_policy_versions_revision"),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint("document_id", "document_version", name="uq_policy_version"),
        sa.UniqueConstraint("release_id"),
    )
    op.create_index("ix_policy_versions_document_id", "policy_versions", ["document_id"])
    op.create_index("ix_policy_versions_state", "policy_versions", ["state"])
    op.create_index("ix_policy_versions_is_active", "policy_versions", ["is_active"])

    op.create_table(
        "policy_sections",
        sa.Column("section_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.String(length=128), nullable=False),
        sa.Column("section", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["version_id"], ["policy_versions.version_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("section_id"),
        sa.UniqueConstraint("version_id", "section", name="uq_policy_section"),
    )
    op.create_index("ix_policy_sections_version_id", "policy_sections", ["version_id"])

    op.create_table(
        "policy_index_entries",
        sa.Column("index_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("document_version", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column("section", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("index_state", sa.String(length=32), nullable=False, server_default="READY"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["policy_versions.version_id"], ondelete="CASCADE"),
        sa.CheckConstraint("index_state IN ('READY', 'STALE')", name="ck_policy_index_state"),
        sa.PrimaryKeyConstraint("index_id"),
        sa.UniqueConstraint("version_id", "section", name="uq_policy_index_section"),
    )
    op.create_index("ix_policy_index_entries_version_id", "policy_index_entries", ["version_id"])
    op.create_index("ix_policy_index_entries_document_id", "policy_index_entries", ["document_id"])
    op.create_index("ix_policy_index_entries_release_id", "policy_index_entries", ["release_id"])

    op.create_table(
        "policy_audit_log",
        sa.Column("audit_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_role", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("document_version", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=True),
        sa.Column("to_state", sa.String(length=32), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index("ix_policy_audit_log_actor_id", "policy_audit_log", ["actor_id"])
    op.create_index("ix_policy_audit_log_action", "policy_audit_log", ["action"])
    op.create_index("ix_policy_audit_log_document_id", "policy_audit_log", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_policy_audit_log_document_id", table_name="policy_audit_log")
    op.drop_index("ix_policy_audit_log_action", table_name="policy_audit_log")
    op.drop_index("ix_policy_audit_log_actor_id", table_name="policy_audit_log")
    op.drop_table("policy_audit_log")
    op.drop_index("ix_policy_index_entries_release_id", table_name="policy_index_entries")
    op.drop_index("ix_policy_index_entries_document_id", table_name="policy_index_entries")
    op.drop_index("ix_policy_index_entries_version_id", table_name="policy_index_entries")
    op.drop_table("policy_index_entries")
    op.drop_index("ix_policy_sections_version_id", table_name="policy_sections")
    op.drop_table("policy_sections")
    op.drop_index("ix_policy_versions_is_active", table_name="policy_versions")
    op.drop_index("ix_policy_versions_state", table_name="policy_versions")
    op.drop_index("ix_policy_versions_document_id", table_name="policy_versions")
    op.drop_table("policy_versions")
    op.drop_table("policy_documents")
