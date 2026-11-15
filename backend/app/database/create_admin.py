"""Bootstrap the first admin: ``ADMIN_PASSWORD=... python -m app.database.create_admin you@clinic.in``.

The password is read from the ADMIN_PASSWORD environment variable or prompted (never a CLI argument,
so it does not end up in shell history).
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys

from app.core.config import get_settings
from app.database.session import get_sessionmaker
from app.models.enums import UserRole
from app.services.auth import AuthService


async def _create(email: str, password: str) -> None:
    async with get_sessionmaker()() as session:
        user = await AuthService(session, get_settings()).create_user(email, password, UserRole.ADMIN, None, None)
    print(f"Created admin {user.email} ({user.id})")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.database.create_admin <email>")
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    asyncio.run(_create(sys.argv[1], password))


if __name__ == "__main__":
    main()
