"""Record the generated-scenario manifest used by each commerce import."""

from alembic import op
import sqlalchemy as sa


revision = "20261122_03"
down_revision = "20261122_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "commerce_imports",
        sa.Column(
            "transformation_manifest_sha256",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
    )
    op.alter_column("commerce_imports", "transformation_manifest_sha256", server_default=None)


def downgrade() -> None:
    op.drop_column("commerce_imports", "transformation_manifest_sha256")
