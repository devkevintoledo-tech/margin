"""Load a catalog release: ``python -m scripts.load_catalog_release <folder | tag> [--force]``.

A tag (``catalog-2026.10.1``) is downloaded from the GitHub Release of that
name unless ``CATALOG_RELEASES_DIR`` already holds its folder. The whole load
is one transaction: any failure leaves the database exactly as it was.
Idempotent: loading a release that is already loaded does nothing.

For a private repository, download the asset with
``gh release download <tag> -D releases/`` and pass the extracted folder.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import tarfile
from pathlib import Path

import httpx

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.catalog_loader import CatalogLoadError, load_release, read_release

_TAG = re.compile(r"^catalog-\d{4}\.\d{2}\.\d+$")


def resolve_release(arg: str, releases_dir: Path, client: httpx.Client | None = None) -> Path:
    """A release folder for ``arg``: a folder path, or a tag fetched and unpacked."""
    path = Path(arg)
    if path.is_dir():
        return path
    tag = arg if arg.startswith("catalog-") else f"catalog-{arg}"
    if not _TAG.match(tag):
        raise CatalogLoadError(f"{arg!r} is neither a release folder nor a catalog-YYYY.MM.N tag")
    folder = releases_dir / tag
    if folder.is_dir():
        return folder
    releases_dir.mkdir(parents=True, exist_ok=True)
    tarball = releases_dir / f"{tag}.tar.gz"
    url = f"{settings.CATALOG_RELEASES_URL}/{tag}/{tag}.tar.gz"
    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=600.0))
    try:
        with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            with tarball.open("wb") as fh:
                for chunk in response.iter_bytes(1 << 20):
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        tarball.unlink(missing_ok=True)
        raise CatalogLoadError(f"could not download {url}: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    with tarfile.open(tarball) as tar:
        tar.extractall(releases_dir, filter="data")  # refuses absolute paths and ../ escapes
    if not folder.is_dir():
        raise CatalogLoadError(f"{tarball.name} did not contain a {tag}/ folder")
    return folder


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.load_catalog_release")
    parser.add_argument("release", help="release folder, or tag such as catalog-2026.10.1")
    parser.add_argument("--force", action="store_true", help="load even if older than the loaded release")
    args = parser.parse_args(argv)
    try:
        release = read_release(resolve_release(args.release, Path(settings.CATALOG_RELEASES_DIR)))
        async with AsyncSessionLocal() as db:
            async with db.begin():
                stats = await load_release(db, release, force=args.force)
    except CatalogLoadError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    if stats.noop:
        print(f"{stats.version} is already loaded; nothing to do")
    else:
        print(f"loaded {stats.version}: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
