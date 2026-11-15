"""Async engine/session factory, serverless-safe.

Neon pooled URLs sit behind PgBouncer, so SQLAlchemy's own pool is disabled
(``NullPool``) to avoid connection exhaustion across function instances.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def normalize_database_url(url: str) -> str:
    """Convert a libpq-style URL into SQLAlchemy+asyncpg form.

    asyncpg rejects ``sslmode``/``channel_binding``; map ``sslmode`` to ``ssl``.
    """
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.pop("channel_binding", None)
    sslmode = query.pop("sslmode", None)
    if sslmode and sslmode != "disable":
        query["ssl"] = "require"
    scheme = "postgresql+asyncpg"
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), ""))


@lru_cache
def get_engine() -> AsyncEngine:
    url = get_settings().database_url.get_secret_value()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_async_engine(normalize_database_url(url), poolclass=NullPool, pool_pre_ping=False)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request; rolls back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
