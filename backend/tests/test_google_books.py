import pytest
import respx
from httpx import Response

from app.services import google_books as gb

SAMPLE_VOLUME = {
    "id": "ABC123",
    "volumeInfo": {
        "title": "The Darkness That Comes Before",
        "subtitle": "Book One",
        "authors": ["R. Scott Bakker"],
        "publisher": "Overlook Press",
        "publishedDate": "2003-05-01",
        "description": "Prince of Nothing, Book One...",
        "industryIdentifiers": [
            {"type": "ISBN_13", "identifier": "9781585675340"},
            {"type": "ISBN_10", "identifier": "1585675342"},
        ],
        "pageCount": 577,
        "categories": ["Fiction / Fantasy / Epic"],
        "averageRating": 4.0,
        "ratingsCount": 42,
        "maturityRating": "NOT_MATURE",
        "language": "en",
        "previewLink": "http://books.google.com/books?id=ABC123",
        "infoLink": "https://books.google.com/books?id=ABC123",
        "imageLinks": {"thumbnail": "http://books.google.com/x?id=ABC123&zoom=1"},
    },
}


def test_map_volume_extracts_all_fields():
    m = gb._map_volume(SAMPLE_VOLUME)
    assert m["external_id"] == "ABC123"
    assert m["title"] == "The Darkness That Comes Before"
    assert m["subtitle"] == "Book One"
    assert m["author"] == "R. Scott Bakker"
    assert m["publisher"] == "Overlook Press"
    assert m["published_date"].isoformat() == "2003-05-01"
    assert m["published_year"] == 2003
    assert m["isbn_13"] == "9781585675340"
    assert m["page_count"] == 577
    assert m["average_rating"] == 4.0
    assert m["ratings_count"] == 42
    assert m["language"] == "en"
    assert m["categories"] == ["Fiction / Fantasy / Epic"]
    assert m["genre_slug"] == "fantasy"
    assert m["cover_url"].startswith("https://")  # http upgraded


def test_map_volume_handles_missing_optional_fields():
    m = gb._map_volume({"id": "X", "volumeInfo": {"title": "Bare"}})
    assert m["external_id"] == "X"
    assert m["title"] == "Bare"
    assert m["author"] == "Unknown"  # NOT NULL fallback
    assert m["cover_url"] is None
    assert m["published_year"] is None
    assert m["genre_slug"] is None


def test_parse_year_from_year_only_date():
    assert gb._parse_year("1998") == 1998
    assert gb._parse_year(None) is None


@pytest.mark.parametrize(
    "category,slug",
    [
        ("Science Fiction", "science-fiction"),
        ("Fiction / Fantasy / Epic", "fantasy"),
        ("Biography & Autobiography", "biography"),
        ("History / Europe", "history"),
        ("Philosophy", "philosophy"),
        ("Poetry", "poetry"),
        ("True Crime / Murder", "mystery"),
        ("Fiction / Literary", "literary-fiction"),
        ("Cooking", None),
    ],
)
def test_category_to_slug(category, slug):
    assert gb._category_to_slug([category]) == slug


@respx.mock
async def test_search_books_maps_results():
    respx.get("https://www.googleapis.com/books/v1/volumes").mock(
        return_value=Response(200, json={"totalItems": 1, "items": [SAMPLE_VOLUME]})
    )
    results = await gb.search_books("darkness")
    assert len(results) == 1
    assert results[0]["external_id"] == "ABC123"


@respx.mock
async def test_search_books_empty_when_no_items():
    respx.get("https://www.googleapis.com/books/v1/volumes").mock(
        return_value=Response(200, json={"totalItems": 0})
    )
    assert await gb.search_books("zzzz") == []


# ---------------------------------------------------------------------------
# Two-pass relevance: title-weighted search first, broad fallback second.
# ---------------------------------------------------------------------------

def _volume(vid: str, title: str | None = None) -> dict:
    return {"id": vid, "volumeInfo": {"title": title if title is not None else vid}}


def _route_by_query(mapping: dict[str, list[dict]]):
    """respx side_effect: return items keyed by the request's `q` param."""

    def handler(request):
        q = request.url.params.get("q")
        return Response(200, json={"items": mapping.get(q, [])})

    return handler


@respx.mock
async def test_search_books_first_pass_uses_intitle_and_country():
    captured = {}

    def handler(request):
        captured["q"] = request.url.params.get("q")
        captured["country"] = request.url.params.get("country")
        captured["orderBy"] = request.url.params.get("orderBy")
        # Enough title hits → no fallback.
        return Response(200, json={"items": [_volume("a"), _volume("b"), _volume("c")]})

    respx.get("https://www.googleapis.com/books/v1/volumes").mock(side_effect=handler)
    await gb.search_books("wuthering heights")
    assert captured["q"] == "intitle:wuthering heights"
    assert captured["country"] == "US"
    assert captured["orderBy"] == "relevance"


@respx.mock
async def test_search_books_no_fallback_when_enough_title_results():
    route = respx.get("https://www.googleapis.com/books/v1/volumes").mock(
        side_effect=_route_by_query(
            {"intitle:dune": [_volume("a"), _volume("b"), _volume("c")]}
        )
    )
    results = await gb.search_books("dune")
    assert [r["external_id"] for r in results] == ["a", "b", "c"]
    assert route.call_count == 1  # broad pass NOT made


@respx.mock
async def test_search_books_falls_back_to_broad_when_few_title_results():
    route = respx.get("https://www.googleapis.com/books/v1/volumes").mock(
        side_effect=_route_by_query(
            {
                "intitle:emily bronte": [_volume("title1")],
                "emily bronte": [_volume("broad1"), _volume("broad2")],
            }
        )
    )
    results = await gb.search_books("emily bronte")
    assert route.call_count == 2  # both passes made
    # Title hit first, then broad results appended.
    assert [r["external_id"] for r in results] == ["title1", "broad1", "broad2"]


@respx.mock
async def test_search_books_fallback_dedupes_by_external_id():
    respx.get("https://www.googleapis.com/books/v1/volumes").mock(
        side_effect=_route_by_query(
            {
                "intitle:grief": [_volume("shared")],
                "grief": [_volume("shared"), _volume("unique")],
            }
        )
    )
    results = await gb.search_books("grief")
    assert [r["external_id"] for r in results] == ["shared", "unique"]


# ---------------------------------------------------------------------------
# _cover_url() — prefer higher-resolution image links, upgrade the URL.
# ---------------------------------------------------------------------------


def test_cover_url_none_for_falsy_input():
    assert gb._cover_url(None) is None
    assert gb._cover_url({}) is None


def test_cover_url_prefers_large_over_thumbnail():
    links = {
        "thumbnail": "https://books.google.com/x?id=A&zoom=5",
        "large": "https://books.google.com/x?id=A&large",
    }
    assert gb._cover_url(links) == "https://books.google.com/x?id=A&large"


def test_cover_url_prefers_largest_available_key():
    links = {
        "smallThumbnail": "https://books.google.com/x?small_thumb",
        "thumbnail": "https://books.google.com/x?thumb",
        "small": "https://books.google.com/x?small",
        "medium": "https://books.google.com/x?medium",
        "large": "https://books.google.com/x?large",
        "extraLarge": "https://books.google.com/x?extra_large",
    }
    assert gb._cover_url(links) == "https://books.google.com/x?extra_large"


def test_cover_url_falls_back_to_thumbnail():
    links = {
        "smallThumbnail": "https://books.google.com/x?small_thumb",
        "thumbnail": "https://books.google.com/x?thumb",
    }
    assert gb._cover_url(links) == "https://books.google.com/x?thumb"


def test_cover_url_falls_back_to_small_thumbnail():
    links = {"smallThumbnail": "https://books.google.com/x?small_thumb"}
    assert gb._cover_url(links) == "https://books.google.com/x?small_thumb"


def test_cover_url_upgrades_http_to_https():
    links = {"thumbnail": "http://books.google.com/x?id=A"}
    assert gb._cover_url(links) == "https://books.google.com/x?id=A"


def test_cover_url_strips_edge_curl_and_bumps_zoom():
    links = {
        "thumbnail": (
            "http://books.google.com/books/content?id=XXX&printsec=frontcover"
            "&img=1&zoom=1&edge=curl&source=gbs_api"
        )
    }
    assert gb._cover_url(links) == (
        "https://books.google.com/books/content?id=XXX&printsec=frontcover"
        "&img=1&zoom=0&source=gbs_api"
    )


def test_cover_url_transforms_apply_to_chosen_high_res_key():
    # Requirement 3 is key-independent: edge/zoom rewrites apply to whichever key
    # wins, not just the thumbnail fallback.
    links = {
        "large": "http://books.google.com/books/content?id=A&zoom=1&edge=curl",
        "thumbnail": "http://books.google.com/x?thumb",
    }
    assert gb._cover_url(links) == (
        "https://books.google.com/books/content?id=A&zoom=0"
    )


# ---------------------------------------------------------------------------
# normalize() helper for dedup matching.
# ---------------------------------------------------------------------------


def test_normalize_lowercases_and_collapses_whitespace():
    assert gb.normalize("  The   Hobbit  ") == "the hobbit"


def test_normalize_strips_accents():
    assert gb.normalize("Les Misérables") == "les miserables"


def test_normalize_strips_punctuation():
    assert gb.normalize("Slaughterhouse-Five!") == "slaughterhouse five"


def test_normalize_handles_empty():
    assert gb.normalize("") == ""
    assert gb.normalize(None) == ""

# ---------------------------------------------------------------------------
# search_books() two-pass merge. Duplicate editions are NOT collapsed here any
# more — work grouping (services/works.py) owns that, by identity rather than
# by string key.
# ---------------------------------------------------------------------------


def _api_volume(ext_id, title, author, *, cover=False):
    info = {"title": title, "authors": [author]}
    if cover:
        info["imageLinks"] = {"thumbnail": f"http://books.google.com/x?id={ext_id}"}
    return {"id": ext_id, "volumeInfo": info}


@respx.mock
@pytest.mark.asyncio
async def test_search_books_merges_both_passes_keeping_every_edition():
    base = gb.settings.GOOGLE_BOOKS_BASE_URL
    title_payload = {
        "items": [
            _api_volume("a", "The Hobbit", "J.R.R. Tolkien"),
            _api_volume("b", "The Hobbit", "J.R.R. Tolkien", cover=True),
        ]
    }
    # Two title hits (< _MIN_TITLE_RESULTS) ⇒ broad pass also runs.
    broad_payload = {"items": [_api_volume("c", "Hobbit Companion", "Other Author")]}

    route = respx.get(f"{base}/volumes")
    route.side_effect = [
        Response(200, json=title_payload),
        Response(200, json=broad_payload),
    ]

    results = await gb.search_books("the hobbit")
    # a and b are duplicate editions and both survive: collapsing them is the
    # work layer's job, and it needs every edition to do it.
    assert [r["external_id"] for r in results] == ["a", "b", "c"]


@respx.mock
@pytest.mark.asyncio
async def test_search_books_skips_the_broad_pass_when_titles_suffice():
    base = gb.settings.GOOGLE_BOOKS_BASE_URL
    title_payload = {
        "items": [
            _api_volume("a", "Dune", "Frank Herbert"),
            _api_volume("b", "Dune", "Frank Herbert", cover=True),
            _api_volume("c", "Dune Messiah", "Frank Herbert"),
            _api_volume("d", "Children of Dune", "Frank Herbert"),
        ]
    }

    route = respx.get(f"{base}/volumes").mock(
        return_value=Response(200, json=title_payload)
    )

    results = await gb.search_books("dune")
    # 4 title hits (>= _MIN_TITLE_RESULTS) ⇒ broad pass NOT made.
    assert route.call_count == 1
    assert [r["external_id"] for r in results] == ["a", "b", "c", "d"]


@respx.mock
@pytest.mark.asyncio
async def test_search_books_does_not_repeat_a_volume_across_passes():
    """A volume returned by both passes appears once, in title-pass order."""
    base = gb.settings.GOOGLE_BOOKS_BASE_URL
    route = respx.get(f"{base}/volumes")
    route.side_effect = [
        Response(200, json={"items": [_api_volume("a", "Dune", "Frank Herbert")]}),
        Response(
            200,
            json={
                "items": [
                    _api_volume("a", "Dune", "Frank Herbert"),
                    _api_volume("z", "Dune Companion", "Someone Else"),
                ]
            },
        ),
    ]

    results = await gb.search_books("dune")
    assert [r["external_id"] for r in results] == ["a", "z"]
