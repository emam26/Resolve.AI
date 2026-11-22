"""Create the pgvector policy embedding index table."""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "20261122_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "policy_embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=255), nullable=False),
        sa.Column("document_version", sa.String(length=64), nullable=False),
        sa.Column("section", sa.String(length=255), nullable=False),
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "document_version",
            "section",
            "release_id",
            name="uq_policy_embedding_revision",
        ),
    )


def downgrade() -> None:
    op.drop_table("policy_embeddings")
