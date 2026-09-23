"""Open Library client — the source of *work identity*.

Google Books has no concept of a work: every edition is an unrelated volume.
Open Library models works and editions natively, so a single call can tell us
that six volumes are one book. This module only ever answers questions; it
never raises on upstream failure, because a search request must still succeed
when Open Library is down (the caller falls back to a local heuristic).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import httpx

from app.config import settings
from app.services.google_books import normalize
from app.services.work_identity import clean_title, normalize_isbn

_TIMEOUT = 10.0
_FIELDS = "key,title,author_name,first_publish_year,edition_count,isbn"

# Solr chokes on unbounded OR clauses, and a Google Books page is 20 volumes.
_ISBN_BATCH = 20


@dataclass(frozen=True)
class OLWork:
    """One Open Library work, reduced to what identity resolution needs."""

    key: str  # bare id, e.g. "OL17076473W"
    title: str
    author: str | None
    first_publish_year: int | None
    edition_count: int
    isbn_13s: frozenset[str]


async def _search(params: dict[str, Any]) -> list[dict[str, Any]]:
    """GET /search.json, returning docs. Any failure yields an empty list."""
    url = f"{settings.OPEN_LIBRARY_BASE_URL}/search.json"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json().get("docs", [])
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
        # Timeout, 429, outage, malformed body — identity resolution degrades
        # to the heuristic tier rather than failing the user's search.
        return []


def _to_work(doc: dict[str, Any]) -> OLWork | None:
    key = (doc.get("key") or "").rsplit("/", 1)[-1]
    title = doc.get("title")
    if not key or not title:
        return None
    authors = doc.get("author_name") or []
    isbns = {normalize_isbn(raw) for raw in (doc.get("isbn") or [])}
    return OLWork(
        key=key,
        title=title,
        author=authors[0] if authors else None,
        first_publish_year=doc.get("first_publish_year"),
        edition_count=doc.get("edition_count") or 0,
        isbn_13s=frozenset(i for i in isbns if i),
    )


async def resolve_by_isbns(isbn_13s: Sequence[str]) -> dict[str, OLWork]:
    """Resolve many ISBNs to their works in as few calls as possible.

    Returns a mapping keyed by the *requested* ISBN. Requested ISBNs with no
    match are simply absent.
    """
    wanted = [i for i in (normalize_isbn(v) for v in isbn_13s) if i]
    if not wanted:
        return {}

    works: list[OLWork] = []
    for start in range(0, len(wanted), _ISBN_BATCH):
        chunk = wanted[start : start + _ISBN_BATCH]
        docs = await _search(
            {
                "q": "isbn:({})".format(" OR ".join(chunk)),
                "fields": _FIELDS,
                "limit": len(chunk),
            }
        )
        works.extend(w for w in (_to_work(d) for d in docs) if w)

    resolved: dict[str, OLWork] = {}
    for isbn in wanted:
        for work in works:
            if isbn in work.isbn_13s:
                resolved[isbn] = work
                break
    return resolved


async def resolve_by_title_author(title: str, author: str) -> OLWork | None:
    """Fall back to a title+author lookup for a volume with no usable ISBN.

    Accepts only an exact normalized title and first-author match. Open Library
    contains duplicate works (``Red Rising`` exists twice), so ties are broken
    on ``edition_count`` — the fuller record is the canonical one.
    """
    if not title or not author:
        return None

    docs = await _search(
        {"title": title, "author": author, "fields": _FIELDS, "limit": 5}
    )
    wanted_title = clean_title(title)
    wanted_author = normalize(author.split(",")[0])

    candidates = []
    for work in (_to_work(d) for d in docs):
        if work is None:
            continue
        if clean_title(work.title) != wanted_title:
            continue
        if normalize(work.author or "") != wanted_author:
            continue
        candidates.append(work)

    if not candidates:
        return None
    return max(candidates, key=lambda w: w.edition_count)
