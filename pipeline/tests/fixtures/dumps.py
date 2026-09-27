"""Builders for tiny Open Library dumps and Wikidata responses."""

from __future__ import annotations

import gzip
import json
from typing import Iterable


def gz(lines: Iterable[str]) -> bytes:
    # mtime=0 keeps the bytes identical run to run.
    return gzip.compress(("\n".join(lines) + "\n").encode("utf-8"), mtime=0)


def dump_line(type_: str, key: str, record: dict) -> str:
    """One row of an OL entity dump: type, key, revision, last_modified, JSON."""
    return "\t".join([type_, key, "1", "2026-08-31T00:00:00", json.dumps(record)])


def edition_line(ol_id: str, work: str, languages=("eng",), **fields) -> str:
    record = {"key": f"/books/{ol_id}", "works": [{"key": f"/works/{work}"}],
              "languages": [{"key": f"/languages/{lang}"} for lang in languages], **fields}
    return dump_line("/type/edition", f"/books/{ol_id}", record)


def sparql_json(rows: list[dict[str, str]]) -> dict:
    def value(v: str) -> dict:
        kind = "uri" if v.startswith("http://www.wikidata.org/entity/") else "literal"
        return {"type": kind, "value": v}
    return {"results": {"bindings": [{k: value(v) for k, v in row.items()} for row in rows]}}


def entity(q: str) -> str:
    return f"http://www.wikidata.org/entity/{q}"
