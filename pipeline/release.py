"""Build the release tables from the group stage's output (spec §4.5)."""

from __future__ import annotations

from typing import Callable

import duckdb
import pyarrow as pa

from pipeline.contract import SCHEMAS

from pipeline.ids import assign_slugs, edition_identity, row_id, series_identity, work_identity
from pipeline._backend import series_key

# The app's column widths (String(500) and friends); longer values would fail the load.
_TEXT_LIMIT = 500


def _clip(value: str | None, limit: int = _TEXT_LIMIT) -> str | None:
    return value[:limit] if value is not None else None


def cover_url(cover_id: int | None) -> str | None:
    return f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cursor = con.execute(sql)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, r)) for r in cursor.fetchall()]


def build_release(con: duckdb.DuckDBPyConnection) -> dict[str, pa.Table]:
    """The five release tables, from the group stage's output, in identity order."""
    work_id: Callable[[str], str] = lambda ol: row_id(work_identity(ol))  # noqa: E731
    sid: Callable[[str], str] = lambda key: row_id(series_identity(key))  # noqa: E731

    series = _rows(con, "SELECT * FROM g_series ORDER BY key")
    slugs = assign_slugs({series_identity(s["key"]): s["name"] for s in series})
    works = _rows(con, "SELECT * FROM g_works ORDER BY ol_id")
    authors = {w["ol_id"]: w["author"] for w in works}
    editions = _rows(con, "SELECT * FROM g_editions ORDER BY ol_id")
    members = _rows(con, "SELECT * FROM g_members ORDER BY series_key, work_ol_id")
    aliases = _rows(con, "SELECT * FROM g_aliases ORDER BY ol_id")

    tables = {
        "works": [{
            "id": work_id(w["ol_id"]), "ol_work_id": w["ol_id"], "canonical_key": w["canonical_key"],
            "title": _clip(w["title"]), "subtitle": _clip(w["subtitle"]), "author": _clip(w["author"]),
            "first_publish_year": w["first_publish_year"], "kind": w["kind"], "series_id": sid(w["room"]),
            "ol_cover_id": w["cover_id"], "ol_edition_count": w["edition_count"],
            "readinglog_count": w["readinglog_count"], "ratings_count": w["ratings_count"],
            "subjects": w["subjects"],
            "representative_edition_id": row_id(edition_identity(w["representative_edition"]))
            if w["representative_edition"] else None,
        } for w in works],
        "editions": [{
            "id": row_id(edition_identity(e["ol_id"])), "ol_edition_id": e["ol_id"],
            "work_id": work_id(e["work_ol_id"]), "title": _clip(e["title"]) or "Untitled",
            "subtitle": _clip(e["subtitle"]), "author": _clip(authors[e["work_ol_id"]]),
            "publisher": _clip(e["publisher"]), "published_year": e["publish_year"], "isbn_13": e["isbn_13"],
            "page_count": e["page_count"], "cover_url": cover_url(e["cover_id"]), "language": "en",
        } for e in editions],
        "series": [{
            "id": sid(s["key"]), "key": s["key"], "source": s["source"], "provenance": s["provenance"],
            "name": _clip(s["name"]), "slug": slugs[series_identity(s["key"])],
            "canonical_key": series_key(s["name"]), "kind": s["kind"],
            "parent_series_id": sid(s["parent_key"]) if s["parent_key"] else None,
        } for s in series],
        "series_members": [{
            "series_id": sid(m["series_key"]), "work_id": work_id(m["work_ol_id"]), "position": m["position"],
            "provenance": m["provenance"], "confidence": m["confidence"],
        } for m in members],
        "work_aliases": [{"ol_work_id": a["ol_id"], "work_id": work_id(a["work_ol_id"])} for a in aliases],
    }
    return {name: pa.Table.from_pylist(rows, schema=SCHEMAS[name]) for name, rows in tables.items()}
