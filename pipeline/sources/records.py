"""Provenance for every input: what was fetched, from where, and its hash."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

_DUMP_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class SourceRecord:
    name: str
    url: str  # the final URL, after Open Library's "latest" redirect
    retrieved: str  # the dump date from the file name, else an ISO timestamp
    size: int
    sha256: str


def dump_date(url: str) -> str | None:
    match = _DUMP_DATE.search(url.rsplit("/", 1)[-1])
    return match.group(1) if match else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_record(dest: Path, record: SourceRecord) -> None:
    """Sidecar next to a downloaded file, so a re-run can skip the download."""
    dest.with_name(dest.name + ".source.json").write_text(json.dumps(asdict(record), sort_keys=True))


def read_record(dest: Path) -> SourceRecord | None:
    sidecar = dest.with_name(dest.name + ".source.json")
    if not (dest.exists() and sidecar.exists()):
        return None
    return SourceRecord(**json.loads(sidecar.read_text()))
