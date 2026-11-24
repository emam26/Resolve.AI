"""Minimal Alembic environment for the PostgreSQL policy embedding table."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.app.db.conversations import Base as ConversationBase
from backend.app.db.refunds import RefundRow  # noqa: F401 - register shared metadata
from backend.app.db.policies import (  # noqa: F401 - register shared metadata
    PolicyAuditRow,
    PolicyIndexRow,
    PolicySectionRow,
    PolicyVersionRow,
)
from backend.app.rag.pgvector_store import Base as PolicyBase
from backend.app.ai.model_control import (  # noqa: F401 - register shared metadata
    ModelRegistryRow,
    QuotaReservationRow,
    QuotaWindowRow,
)


config = context.config
configured_url = os.getenv("RESOLVEAI_DATABASE_URL")
if configured_url:
    config.set_main_option("sqlalchemy.url", configured_url.replace("%", "%%"))

target_metadata = [PolicyBase.metadata, ConversationBase.metadata]


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
