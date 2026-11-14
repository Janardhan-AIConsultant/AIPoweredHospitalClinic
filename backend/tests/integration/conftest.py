"""Integration fixtures: real PostgreSQL, schema built by running the actual Alembic migration.

Set TEST_DATABASE_URL (default: local docker-compose Postgres). WARNING: the target
database's ``public`` schema is DROPPED and recreated - never point this at Neon production.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database.session import normalize_database_url

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://clinic:clinic_dev_only@localhost:5432/clinic")
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _guard(url: str) -> None:
    if "neon.tech" in url and os.environ.get("ALLOW_NEON_TEST_DB") != "1":
        raise RuntimeError("Refusing to run destructive tests against a Neon database")


async def _reset_schema(url: str) -> None:
    engine = create_async_engine(normalize_database_url(url), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session")
def migrated_db() -> str:
    _guard(TEST_URL)
    try:
        asyncio.run(_reset_schema(TEST_URL))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable at TEST_DATABASE_URL: {type(exc).__name__}")
    env = {**os.environ, "MIGRATION_DATABASE_URL": TEST_URL}
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True
    )
    return TEST_URL


@pytest_asyncio.fixture
async def engine(migrated_db: str):
    eng = create_async_engine(normalize_database_url(migrated_db), poolclass=NullPool)
    async with eng.begin() as conn:
        tables = (
            (
                await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")
                )
            )
            .scalars()
            .all()
        )
        await conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE"))
    yield eng
    await eng.dispose()


@pytest.fixture
def maker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
