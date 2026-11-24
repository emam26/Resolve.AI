"""Add durable model registry and quota-control tables."""

from alembic import op
import sqlalchemy as sa


revision = "20261124_07"
down_revision = "20261123_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_model_registry",
        sa.Column("model_key", sa.String(length=384), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("health_state", sa.String(length=32), nullable=False, server_default="HEALTHY"),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("free_eligible", sa.Boolean(), nullable=True),
        sa.Column("privacy_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("structured_output_supported", sa.Boolean(), nullable=True),
        sa.Column("pricing_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("rate_limits_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("input_token_limit", sa.Integer(), nullable=True),
        sa.Column("output_token_limit", sa.Integer(), nullable=True),
        sa.Column("capabilities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("upstream_provider", sa.String(length=128), nullable=True),
        sa.Column("quota_scope", sa.String(length=255), nullable=False),
        sa.Column("catalog_version", sa.String(length=128), nullable=False),
        sa.Column("evaluation_version", sa.String(length=128), nullable=True),
        sa.Column("benchmark_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("runtime_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("health_cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("model_key"),
        sa.UniqueConstraint("provider", "model_id", name="uq_ai_model_provider_id"),
        sa.CheckConstraint(
            "lifecycle IN ('DISCOVERED', 'UNVERIFIED', 'QUALIFIED', 'ACTIVE', 'DEGRADED', 'RATE_LIMITED', 'QUARANTINED', 'DISABLED', 'DEPRECATED')",
            name="ck_ai_model_lifecycle",
        ),
        sa.CheckConstraint(
            "health_state IN ('HEALTHY', 'DEGRADED', 'RATE_LIMITED', 'QUARANTINED')",
            name="ck_ai_model_health_state",
        ),
    )
    op.create_index("ix_ai_model_registry_provider", "ai_model_registry", ["provider"])
    op.create_index("ix_ai_model_registry_lifecycle", "ai_model_registry", ["lifecycle"])

    op.create_table(
        "ai_quota_windows",
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("request_limit", sa.Integer(), nullable=False),
        sa.Column("token_limit", sa.Integer(), nullable=False),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False),
        sa.Column("requests_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("in_flight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope_key"),
        sa.CheckConstraint("request_limit > 0", name="ck_ai_quota_request_limit"),
        sa.CheckConstraint("token_limit > 0", name="ck_ai_quota_token_limit"),
        sa.CheckConstraint("concurrency_limit > 0", name="ck_ai_quota_concurrency_limit"),
    )
    op.create_index("ix_ai_quota_windows_provider", "ai_quota_windows", ["provider"])

    op.create_table(
        "ai_quota_reservations",
        sa.Column("reservation_id", sa.String(length=128), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False),
        sa.Column("actual_tokens", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("reservation_id"),
        sa.CheckConstraint("estimated_tokens > 0", name="ck_ai_quota_estimated_tokens"),
        sa.CheckConstraint(
            "state IN ('RESERVED', 'COMPLETED', 'RELEASED', 'RECONCILED')",
            name="ck_ai_quota_reservation_state",
        ),
    )
    op.create_index("ix_ai_quota_reservations_scope_key", "ai_quota_reservations", ["scope_key"])
    op.create_index("ix_ai_quota_reservations_state", "ai_quota_reservations", ["state"])


def downgrade() -> None:
    op.drop_index("ix_ai_quota_reservations_state", table_name="ai_quota_reservations")
    op.drop_index("ix_ai_quota_reservations_scope_key", table_name="ai_quota_reservations")
    op.drop_table("ai_quota_reservations")
    op.drop_index("ix_ai_quota_windows_provider", table_name="ai_quota_windows")
    op.drop_table("ai_quota_windows")
    op.drop_index("ix_ai_model_registry_lifecycle", table_name="ai_model_registry")
    op.drop_index("ix_ai_model_registry_provider", table_name="ai_model_registry")
    op.drop_table("ai_model_registry")
