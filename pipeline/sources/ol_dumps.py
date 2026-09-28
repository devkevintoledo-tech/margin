"""Open Library dump downloads: resumable, verified, recorded."""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Callable

import httpx

from pipeline.sources.http import check_status, with_retries
from pipeline.sources.records import SourceRecord, dump_date, read_record, sha256_file, write_record


class DownloadError(RuntimeError):
    pass


def _fetch_into(client: httpx.Client, url: str, part: Path) -> str:
    """Append the rest of ``url`` to ``part`` (HTTP Range); return the final URL."""
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
        if response.status_code == 416:  # nothing left to send: the part is complete
            return str(response.url)
        check_status(response)
        mode = "ab" if response.status_code == 206 else "wb"
        with part.open(mode) as fh:
            for chunk in response.iter_bytes(1 << 20):
                fh.write(chunk)
        return str(response.url)


def verify_gzip(path: Path) -> None:
    """Decompress end to end: gzip's CRC-32 and length trailer catch corruption."""
    try:
        with gzip.open(path, "rb") as fh:
            while fh.read(1 << 24):
                pass
    except (OSError, EOFError) as exc:
        path.unlink(missing_ok=True)
        raise DownloadError(f"{path.name} failed verification: {exc}") from exc


def download(client: httpx.Client, name: str, url: str, dest: Path, *,
             attempts: int = 5, sleep: Callable[[float], None]) -> SourceRecord:
    """Download ``url`` to ``dest`` once; later calls return the recorded source."""
    existing = read_record(dest)
    if existing is not None:
        return existing
    part = dest.with_name(dest.name + ".part")
    final_url = with_retries(
        lambda: _fetch_into(client, url, part),
        attempts=attempts, sleep=sleep,
        give_up=lambda exc: DownloadError(f"{name}: {exc}"),
    )
    verify_gzip(part)
    part.rename(dest)
    record = SourceRecord(name, final_url, dump_date(final_url) or "", dest.stat().st_size, sha256_file(dest))
    write_record(dest, record)
    return record
