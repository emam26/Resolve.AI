"""Add grouped reservations and durable quota reset intervals."""

from alembic import op
import sqlalchemy as sa


revision = "20261124_08"
down_revision = "20261124_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_quota_windows") as batch:
        batch.add_column(
            sa.Column(
                "window_seconds",
                sa.Integer(),
                nullable=False,
                server_default="86400",
            )
        )
        batch.create_check_constraint(
            "ck_ai_quota_window_seconds",
            "window_seconds > 0",
        )

    with op.batch_alter_table("ai_quota_reservations") as batch:
        batch.add_column(sa.Column("reservation_group", sa.String(length=128), nullable=True))

    op.execute(
        sa.text(
            "UPDATE ai_quota_reservations "
            "SET reservation_group = reservation_id "
            "WHERE reservation_group IS NULL"
        )
    )

    with op.batch_alter_table("ai_quota_reservations") as batch:
        batch.alter_column("reservation_group", existing_type=sa.String(length=128), nullable=False)
        batch.create_index(
            "ix_ai_quota_reservations_reservation_group",
            ["reservation_group"],
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_quota_reservations") as batch:
        batch.drop_index("ix_ai_quota_reservations_reservation_group")
        batch.drop_column("reservation_group")

    with op.batch_alter_table("ai_quota_windows") as batch:
        batch.drop_constraint("ck_ai_quota_window_seconds", type_="check")
        batch.drop_column("window_seconds")
