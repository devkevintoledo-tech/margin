"""Write in-app librarian fixes as pipeline overrides.

``python -m scripts.export_overrides [--out pipeline/overrides/z-librarian.yaml] [--check]``

Run from a workstation against the production DATABASE_URL, then review and
commit the file like any other change. ``--check`` writes nothing and exits 1
when the file on disk differs. Runtime-only fixes are listed, not exported.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.database import AsyncSessionLocal
from app.services.librarian.export import exportable, render, runtime_only

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "pipeline" / "overrides" / "z-librarian.yaml"


async def run(db, out: Path, check: bool) -> int:
    text = render(await exportable(db))
    for c, username in await runtime_only(db):
        print(f"runtime-only  {str(c.id)[:8]}  {c.op.value}  {username}: {c.runtime_only_reason}")
    if check:
        current = out.read_text(encoding="utf-8") if out.exists() else None
        if current != text:
            print(f"{out} is out of date; run without --check to rewrite it", file=sys.stderr)
            return 1
        print(f"{out} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.export_overrides")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    async with AsyncSessionLocal() as db:
        return await run(db, args.out, args.check)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
