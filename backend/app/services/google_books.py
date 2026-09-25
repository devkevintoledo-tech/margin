from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any

import httpx

from app.config import settings

# Maps a substring (checked against the lowercased category string) to a seeded
# Genre slug. Order matters — more specific terms first; generic "fiction" last.
_CATEGORY_SLUGS: list[tuple[str, str]] = [
    ("science fiction", "science-fiction"),
    ("fantasy", "fantasy"),
    ("biography", "biography"),
    ("autobiography", "biography"),
    ("history", "history"),
    ("philosophy", "philosophy"),
    ("poetry", "poetry"),
    ("mystery", "mystery"),
    ("detective", "mystery"),
    ("crime", "mystery"),
    ("literary", "literary-fiction"),
    ("fiction", "literary-fiction"),  # generic fiction fallback (last)
]


def normalize(text: str | None) -> str:
    """Canonicalize a string for duplicate matching.

    NFKD-strip accents, lowercase, drop punctuation, collapse whitespace.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = no_accents.lower()
    no_punct = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", no_punct).strip()


def _category_to_slug(categories: list[str] | None) -> str | None:
    if not categories:
        return None
    blob = " ".join(categories).lower()
    for needle, slug in _CATEGORY_SLUGS:
        if needle in blob:
            return slug
    return None


def _parse_year(published_date: str | None) -> int | None:
    if not published_date:
        return None
    head = published_date[:4]
    return int(head) if head.isdigit() else None


def _parse_date(published_date: str | None) -> date | None:
    if not published_date:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(published_date, fmt).date()
        except ValueError:
            continue
    return None


def _isbn_13(identifiers: list[dict[str, Any]] | None) -> str | None:
    """The volume's ISBN as 13 normalized digits, or None.

    Normalized here, at the edge, for three reasons: Google returns hyphenated
    values that would overflow ``Book.isbn_13`` (String(13)); work resolution
    looks editions up in a dict keyed by normalized ISBNs, so an unnormalized
    one silently misses tier 1; and a volume carrying only an ISBN-10 has a
    perfectly good identity once upgraded.
    """
    # Imported inside the function: work_identity imports `normalize` from this
    # module, so a module-level import here would be circular.
    from app.services.work_identity import normalize_isbn

    found = {
        ident.get("type"): ident.get("identifier") for ident in identifiers or []
    }
    return normalize_isbn(found.get("ISBN_13")) or normalize_isbn(found.get("ISBN_10"))


# Highest-resolution first; Google Books only returns a subset per volume.
_COVER_KEYS = ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail")


def _upgrade_cover_url(url: str) -> str:
    """Apply the recoverable URL string transforms to a Google Books cover URL.

    Force https, drop the fake page-curl effect, and request a larger render.
    Each replace is a no-op when its substring isn't present, so this is
    idempotent and safe to run on already-upgraded URLs.
    """
    url = url.replace("http://", "https://", 1)
    return url.replace("&edge=curl", "").replace("zoom=1", "zoom=0")


def _cover_url(image_links: dict[str, Any] | None) -> str | None:
    if not image_links:
        return None
    url = next((image_links[k] for k in _COVER_KEYS if image_links.get(k)), None)
    if not url:
        return None
    return _upgrade_cover_url(url)


def _map_volume(volume: dict[str, Any]) -> dict[str, Any]:
    info = volume.get("volumeInfo", {})
    authors = info.get("authors") or []
    published = info.get("publishedDate")
    categories = info.get("categories")
    return {
        "external_id": volume.get("id"),
        "source": "google_books",
        "title": info.get("title"),
        "subtitle": info.get("subtitle"),
        "author": ", ".join(authors) if authors else "Unknown",
        "publisher": info.get("publisher"),
        "published_date": _parse_date(published),
        "published_year": _parse_year(published),
        "description": info.get("description"),
        "isbn_13": _isbn_13(info.get("industryIdentifiers")),
        "page_count": info.get("pageCount"),
        "average_rating": info.get("averageRating"),
        "ratings_count": info.get("ratingsCount"),
        "language": info.get("language"),
        "categories": categories,
        "maturity_rating": info.get("maturityRating"),
        "info_link": info.get("infoLink"),
        "preview_link": info.get("previewLink"),
        "cover_url": _cover_url(info.get("imageLinks")),
        "genre_slug": _category_to_slug(categories),
    }


def _params(**extra: Any) -> dict[str, Any]:
    params = dict(extra)
    if settings.GOOGLE_BOOKS_API_KEY:
        params["key"] = settings.GOOGLE_BOOKS_API_KEY
    return params


# Below this many title-matched hits, supplement with a broad full-text pass so
# we don't lose recall on author/topic searches that have no title match.
_MIN_TITLE_RESULTS = 3


async def _query_volumes(client: httpx.AsyncClient, q: str) -> list[dict[str, Any]]:
    url = f"{settings.GOOGLE_BOOKS_BASE_URL}/volumes"
    response = await client.get(
        url,
        params=_params(
            q=q,
            maxResults=20,
            printType="books",
            orderBy="relevance",
            country="US",
        ),
    )
    response.raise_for_status()
    data = response.json()
    return [_map_volume(item) for item in data.get("items", []) if item.get("id")]


async def search_books(query: str) -> list[dict[str, Any]]:
    """Two-pass search: title-weighted first, broad full-text fallback.

    A bare ``q=`` matches the phrase anywhere in the corpus (including book
    contents), which buries the actual book under works that merely discuss it.
    Searching ``intitle:`` first surfaces the real title; we only fall back to a
    broad pass when the title search is too thin (e.g. author/topic queries).

    Duplicate editions are no longer collapsed here — work grouping
    (``services/works.py``) does that persistently and by identity, so a second
    string-keyed pass would only disagree with it at the seams.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        title_results = await _query_volumes(client, f"intitle:{query}")
        if len(title_results) >= _MIN_TITLE_RESULTS:
            return title_results

        broad_results = await _query_volumes(client, query)

    seen = {r["external_id"] for r in title_results}
    merged = list(title_results)
    merged.extend(r for r in broad_results if r["external_id"] not in seen)
    return merged


async def get_book(volume_id: str) -> dict[str, Any]:
    url = f"{settings.GOOGLE_BOOKS_BASE_URL}/volumes/{volume_id}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, params=_params())
        response.raise_for_status()
        return _map_volume(response.json())
