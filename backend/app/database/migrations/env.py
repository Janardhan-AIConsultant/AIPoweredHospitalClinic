"""Alembic environment (async). Migrations use the UNPOOLED/direct URL when provided.

URL precedence: MIGRATION_DATABASE_URL > DATABASE_URL_UNPOOLED > DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (register all tables)
from app.core.config import get_settings
from app.database.base import Base
from app.database.session import normalize_database_url

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = (
        os.environ.get("MIGRATION_DATABASE_URL")
        or os.environ.get("DATABASE_URL_UNPOOLED")
        or get_settings().database_url.get_secret_value()
    )
    if not url:
        raise RuntimeError("Set MIGRATION_DATABASE_URL, DATABASE_URL_UNPOOLED or DATABASE_URL")
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
