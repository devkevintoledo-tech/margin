"""Grant or revoke librarian: ``python -m scripts.grant_librarian <username> [--revoke]``.

Idempotent. An unknown username exits 1.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User


async def grant(db, username: str, revoke: bool = False) -> bool:
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        return False
    user.is_librarian = not revoke
    await db.flush()
    return True


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.grant_librarian")
    parser.add_argument("username")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args(argv)
    async with AsyncSessionLocal() as db:
        if not await grant(db, args.username, args.revoke):
            print(f"no user named {args.username!r}", file=sys.stderr)
            return 1
        await db.commit()
    print(f"{'revoked' if args.revoke else 'granted'} librarian: {args.username}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
