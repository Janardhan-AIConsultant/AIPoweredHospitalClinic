"""Create a fresh e2e database: schema via Alembic, demo catalogue, one admin and one doctor account.

Run by Playwright's global setup. Refuses anything that is not a local ``*_e2e`` database.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.database.seed import seed_demo_data
from app.database.session import get_sessionmaker, normalize_database_url
from app.models import Doctor
from app.models.enums import UserRole
from app.services.auth import AuthService

PASSWORD = os.environ.get("E2E_PASSWORD", "E2e-Passw0rd-123")


async def main() -> None:
    url = os.environ["DATABASE_URL"]
    if not url.split("?")[0].endswith("_e2e") or "neon.tech" in url:
        raise SystemExit("Refusing to reset a database that is not a local *_e2e database")
    engine = create_async_engine(normalize_database_url(url), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "MIGRATION_DATABASE_URL": url},
        check=True,
    )
    async with get_sessionmaker()() as session:
        await seed_demo_data(session)
        await session.commit()
        anil = await session.scalar(select(Doctor.id).where(Doctor.full_name == "Dr. Anil Kumar"))
        auth = AuthService(session, get_settings())
        await auth.create_user("admin@e2e.test", PASSWORD, UserRole.ADMIN, None, None)
        await auth.create_user("anil@e2e.test", PASSWORD, UserRole.DOCTOR, anil, None)
    print("e2e database ready")


if __name__ == "__main__":
    asyncio.run(main())
