"""Add durable production session and admission state."""

from alembic import op
import sqlalchemy as sa


revision = "20261124_10"
down_revision = "20261124_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(token_digest) = 64",
            name="ck_auth_session_digest",
        ),
        sa.CheckConstraint(
            "length(username) BETWEEN 1 AND 128",
            name="ck_auth_session_username",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_auth_session_expiry",
        ),
        sa.PrimaryKeyConstraint("token_digest"),
    )
    op.create_index("ix_auth_sessions_username", "auth_sessions", ["username"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "auth_admission_windows",
        sa.Column("bucket_key", sa.String(length=256), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(bucket_key) BETWEEN 1 AND 256",
            name="ck_auth_admission_key",
        ),
        sa.CheckConstraint(
            "window_seconds > 0",
            name="ck_auth_admission_window",
        ),
        sa.CheckConstraint(
            "event_count >= 0",
            name="ck_auth_admission_count",
        ),
        sa.PrimaryKeyConstraint("bucket_key"),
    )


def downgrade() -> None:
    op.drop_table("auth_admission_windows")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_username", table_name="auth_sessions")
    op.drop_table("auth_sessions")
