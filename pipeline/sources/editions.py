"""Stream the editions dump through a filter; the unfiltered file never lands on disk.

The editions dump is larger than the build machine's free space, so it is
decompressed in memory and only English editions of selected works (plus
editions Wikidata links to) are kept.
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from collections import Counter
from typing import Callable, Iterable, Mapping, Protocol

import httpx
import pyarrow as pa

from pipeline.sources.http import RetryableError, check_status, with_retries
from pipeline.sources.ol_dumps import DownloadError
from pipeline.sources.records import SourceRecord, dump_date

EDITION_SCHEMA = pa.schema([
    ("ol_id", pa.string()),
    ("work_ol_id", pa.string()),
    ("is_english", pa.bool_()),
    ("title", pa.string()),
    ("subtitle", pa.string()),
    ("publishers", pa.list_(pa.string())),
    ("publish_date", pa.string()),
    ("isbn_13", pa.list_(pa.string())),
    ("isbn_10", pa.list_(pa.string())),
    ("number_of_pages", pa.int64()),
    ("covers", pa.list_(pa.int64())),
    ("series", pa.list_(pa.string())),
])
# Cheap pre-filters: a regex and a substring test instead of parsing ~50M JSON documents.
_WORK_KEY = re.compile(r'"works":\s*\[\s*\{\s*"key":\s*"/works/(OL\d+W)"')
_ENGLISH = '"/languages/eng"'


class EditionSink(Protocol):
    def reset(self) -> None: ...
    def write(self, batch: pa.Table) -> None: ...


def _strings(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _ints(value) -> list[int]:
    return [v for v in value if isinstance(v, int) and v > 0] if isinstance(value, list) else []


def edition_row(ol_id: str, work: str | None, is_english: bool, record: dict) -> dict:
    pages = record.get("number_of_pages")
    return {
        "ol_id": ol_id,
        "work_ol_id": work,
        "is_english": is_english,
        "title": record.get("title") if isinstance(record.get("title"), str) else None,
        "subtitle": record.get("subtitle") if isinstance(record.get("subtitle"), str) else None,
        "publishers": _strings(record.get("publishers")),
        "publish_date": record.get("publish_date") if isinstance(record.get("publish_date"), str) else None,
        "isbn_13": _strings(record.get("isbn_13")),
        "isbn_10": _strings(record.get("isbn_10")),
        "number_of_pages": pages if isinstance(pages, int) and pages > 0 else None,
        "covers": _ints(record.get("covers")),
        "series": _strings(record.get("series")),
    }


def _lines(chunks: Iterable[bytes], on_chunk: Callable[[bytes], None]) -> Iterable[bytes]:
    decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
    buffer = b""
    for chunk in chunks:
        on_chunk(chunk)
        data = decomp.decompress(chunk)
        while decomp.unused_data:  # a multi-member gzip starts a new member
            rest = decomp.unused_data
            decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
            data += decomp.decompress(rest)
        buffer += data
        *complete, buffer = buffer.split(b"\n")
        yield from complete
    if buffer:
        yield buffer
    if not decomp.eof:
        raise RetryableError("editions stream ended before the gzip trailer")


def stream_editions(client: httpx.Client, url: str, candidates: set[str], wd_editions: set[str],
                    sink: EditionSink, *, resolve: Mapping[str, str] | None = None,
                    attempts: int = 3, sleep: Callable[[float], None],
                    batch_size: int = 50_000) -> tuple[SourceRecord, Counter[str]]:
    """Keep English editions of ``candidates`` and every edition in ``wd_editions``.

    Returns the source record and, for every candidate work, its edition count
    in all languages (Open Library's total, which the app shows). ``resolve``
    maps a redirected work id to its target. A failure restarts the stream
    from the beginning: a gzip stream cannot resume mid-member.
    """
    resolve = resolve or {}

    def attempt() -> tuple[SourceRecord, Counter[str]]:
        sink.reset()
        counts: Counter[str] = Counter()
        digest = hashlib.sha256()
        size = 0
        rows: list[dict] = []

        def on_chunk(chunk: bytes) -> None:
            nonlocal size
            digest.update(chunk)
            size += len(chunk)

        with client.stream("GET", url, follow_redirects=True) as response:
            check_status(response)
            final_url = str(response.url)
            for raw in _lines(response.iter_bytes(1 << 20), on_chunk):
                line = raw.decode("utf-8", errors="replace")
                parts = line.split("\t", 4)
                if len(parts) < 5:
                    continue
                ol_id = parts[1].rsplit("/", 1)[-1]
                match = _WORK_KEY.search(parts[4])
                work = resolve.get(match.group(1), match.group(1)) if match else None
                if work in candidates:
                    counts[work] += 1
                english = _ENGLISH in parts[4]
                if not ((english and work in candidates) or ol_id in wd_editions):
                    continue
                try:
                    record = json.loads(parts[4])
                except json.JSONDecodeError:
                    continue
                rows.append(edition_row(ol_id, work, english, record))
                if len(rows) >= batch_size:
                    sink.write(pa.Table.from_pylist(rows, schema=EDITION_SCHEMA))
                    rows.clear()
        if rows:
            sink.write(pa.Table.from_pylist(rows, schema=EDITION_SCHEMA))
        return SourceRecord("editions", final_url, dump_date(final_url) or "", size, digest.hexdigest()), counts

    return with_retries(attempt, attempts=attempts, sleep=sleep,
                        give_up=lambda exc: DownloadError(f"editions: {exc}"))
