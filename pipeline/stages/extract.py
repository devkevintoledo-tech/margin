"""extract (spec §4.3): normalise selected works, their English editions and authors."""

from __future__ import annotations

import json
from typing import Callable, Iterable, Mapping, NamedTuple

import pyarrow as pa

from pipeline._backend import canonical_key, classify_kind, display_title, join_subjects, normalize_isbn
from pipeline.config import BuildContext
from pipeline.db import iter_rows, swap_in, write_table
from pipeline.sources.load_raw import resolver
from pipeline.sources.ol_records import author_ids, strings, text, year_of

WORKS_SCHEMA = pa.schema([
    ("ol_id", pa.string()), ("raw_title", pa.string()), ("title", pa.string()), ("subtitle", pa.string()),
    ("author", pa.string()), ("author_ids", pa.list_(pa.string())), ("first_publish_year", pa.int32()),
    ("subjects", pa.string()), ("cover_id", pa.int64()), ("ratings_count", pa.int32()),
    ("readinglog_count", pa.int32()), ("edition_count", pa.int32()), ("canonical_key", pa.string()),
    ("kind", pa.string()),
])
EDITIONS_SCHEMA = pa.schema([
    ("ol_id", pa.string()), ("work_ol_id", pa.string()), ("title", pa.string()), ("subtitle", pa.string()),
    ("publisher", pa.string()), ("publish_year", pa.int32()), ("isbn_13", pa.string()),
    ("page_count", pa.int32()), ("cover_id", pa.int64()), ("series", pa.list_(pa.string())),
])
AUTHORS_SCHEMA = pa.schema([
    ("ol_id", pa.string()), ("name", pa.string()), ("alternate_names", pa.list_(pa.string())),
    ("wikidata", pa.string()),
])


class AuthorRow(NamedTuple):
    name: str
    alternate_names: tuple[str, ...]
    wikidata: str | None


def author_row(record: dict) -> AuthorRow:
    remote = record.get("remote_ids") if isinstance(record.get("remote_ids"), dict) else {}
    return AuthorRow(text(record.get("name")) or "", tuple(strings(record.get("alternate_names"))),
                     text(remote.get("wikidata")))


def extract_work(ol_id: str, record: dict, authors: Mapping[str, AuthorRow],
                 resolve_author: Callable[[str], str] = lambda a: a,
                 popularity: tuple[int, int] = (0, 0), edition_count: int = 0,
                 edition_years: Iterable[int] = ()) -> dict:
    raw_title = text(record.get("title")) or ""
    subtitle = text(record.get("subtitle"))
    ids: list[str] = []
    for a in author_ids(record):
        resolved = resolve_author(a)
        if resolved not in ids:
            ids.append(resolved)
    names = [authors[a].name for a in ids if a in authors and authors[a].name]
    title = display_title(raw_title) or raw_title or "Untitled"
    covers = [c for c in record.get("covers") or [] if isinstance(c, int) and c > 0]
    return {
        "ol_id": ol_id,
        "raw_title": raw_title,
        "title": title,
        "subtitle": subtitle,
        "author": ", ".join(names) or "Unknown",
        "author_ids": ids,
        "first_publish_year": year_of(record.get("first_publish_date")) or min(edition_years, default=None),
        "subjects": join_subjects(strings(record.get("subjects"))),
        "cover_id": covers[0] if covers else None,
        "ratings_count": popularity[0],
        "readinglog_count": popularity[1],
        "edition_count": edition_count,
        "canonical_key": canonical_key(title, names[0] if names else None),
        "kind": classify_kind(raw_title, subtitle),
    }


def extract_edition(row: dict) -> dict:
    isbn = next((n for n in map(normalize_isbn, [*row["isbn_13"], *row["isbn_10"]]) if n), None)
    return {
        "ol_id": row["ol_id"], "work_ol_id": row["work_ol_id"], "title": row["title"] or "",
        "subtitle": row["subtitle"], "publisher": row["publishers"][0] if row["publishers"] else None,
        "publish_year": year_of(row["publish_date"]), "isbn_13": isbn, "page_count": row["number_of_pages"],
        "cover_id": row["covers"][0] if row["covers"] else None, "series": row["series"],
    }


def run(ctx: BuildContext) -> None:
    con = ctx.con
    resolve_author = resolver(dict(con.execute("SELECT from_ol, to_ol FROM raw_author_redirects").fetchall()))
    raw_authors = {ol: author_row(json.loads(blob)) for ol, blob in iter_rows(con, "SELECT ol_id, json FROM raw_authors")}
    popularity = {ol: (r, l) for ol, r, l in con.execute(
        "SELECT ol_id, ratings_count, readinglog_count FROM raw_popularity").fetchall()}
    counts = dict(con.execute("SELECT ol_id, edition_count FROM raw_edition_counts").fetchall())

    cursor = con.execute("""
        SELECT e.* FROM raw_editions e JOIN selected s ON e.work_ol_id = s.ol_id
        WHERE e.is_english ORDER BY e.ol_id""")
    columns = [d[0] for d in cursor.description]
    editions = [extract_edition(dict(zip(columns, r))) for r in cursor.fetchall()]
    years: dict[str, list[int]] = {}
    for e in editions:
        if e["publish_year"]:
            years.setdefault(e["work_ol_id"], []).append(e["publish_year"])

    works = [
        extract_work(ol, json.loads(blob), raw_authors, resolve_author, popularity.get(ol, (0, 0)),
                     counts.get(ol, 0), years.get(ol, ()))
        for ol, blob in iter_rows(con, "SELECT w.ol_id, w.json FROM raw_works w JOIN selected s USING (ol_id) ORDER BY w.ol_id")
    ]
    used = sorted({a for w in works for a in w["author_ids"] if a in raw_authors})
    authors = [{"ol_id": a, **raw_authors[a]._asdict()} for a in used]
    for a in authors:
        a["alternate_names"] = list(a["alternate_names"])

    write_table(con, "works", pa.Table.from_pylist(works, schema=WORKS_SCHEMA))
    write_table(con, "editions", pa.Table.from_pylist(editions, schema=EDITIONS_SCHEMA))
    write_table(con, "authors", pa.Table.from_pylist(authors, schema=AUTHORS_SCHEMA))
    swap_in(con, ["works", "editions", "authors"])
