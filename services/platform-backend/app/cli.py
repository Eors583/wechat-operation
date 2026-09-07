from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.config import Settings
from app.database import Database
from app.models import Admin
from app.security import hash_password


async def create_admin(username: str, password: str) -> None:
    settings = Settings.from_env()
    database = Database(settings)
    try:
        async with database.session_maker() as session:
            existing = await session.scalar(select(Admin).where(Admin.username == username))
            if existing:
                raise SystemExit("Administrator already exists")
            session.add(
                Admin(
                    username=username,
                    password_hash=hash_password(password),
                    permissions=["*"],
                )
            )
            await session.commit()
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="wechat-admin")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-admin")
    create.add_argument("--username", required=True)
    create.add_argument("--password", required=True)
    args = parser.parse_args()
    if args.command == "create-admin":
        asyncio.run(create_admin(args.username, args.password))


if __name__ == "__main__":
    main()
