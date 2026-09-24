import httpx
import respx
from httpx import Response

from app.services import open_library as ol

SEARCH_URL = "https://openlibrary.org/search.json"

# Shaped like the live response. Note the mixed ISBN-10 / ISBN-13 forms — this
# is real, and the reason every identifier goes through normalize_isbn().
RED_RISING_DOC = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2014,
    "edition_count": 26,
    "isbn": ["0345539788", "9780345539809", "3453269578"],
}
GOLDEN_SON_DOC = {
    "key": "/works/OL19340986W",
    "title": "Golden Son",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2015,
    "edition_count": 21,
    "isbn": ["9781473646506"],
}


@respx.mock
async def test_resolve_by_isbns_maps_each_requested_isbn_to_its_work():
    respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": [RED_RISING_DOC, GOLDEN_SON_DOC]})
    )
    got = await ol.resolve_by_isbns(["9780345539809", "9781473646506"])
    assert got["9780345539809"].key == "OL17076473W"
    assert got["9781473646506"].key == "OL19340986W"
    assert got["9780345539809"].edition_count == 26


@respx.mock
async def test_resolve_by_isbns_matches_through_an_isbn_10_in_the_work():
    # We hold the 13 form; OL lists the 10 form. They must still match.
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    got = await ol.resolve_by_isbns(["9780345539786"])  # == 0345539788 upgraded
    assert got["9780345539786"].key == "OL17076473W"


@respx.mock
async def test_resolve_by_isbns_returns_empty_without_isbns():
    route = respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": []}))
    assert await ol.resolve_by_isbns([]) == {}
    assert not route.called  # no pointless upstream call


@respx.mock
async def test_resolve_by_isbns_survives_upstream_failure():
    respx.get(SEARCH_URL).mock(return_value=Response(429, json={"error": "slow down"}))
    assert await ol.resolve_by_isbns(["9780345539809"]) == {}


@respx.mock
async def test_resolve_by_isbns_survives_network_error():
    respx.get(SEARCH_URL).mock(side_effect=httpx.ConnectError("boom"))
    assert await ol.resolve_by_isbns(["9780345539809"]) == {}


@respx.mock
async def test_resolve_by_title_author_prefers_the_work_with_more_editions():
    # Open Library itself holds duplicate works for Red Rising; the one with
    # 26 editions is the canonical one.
    duplicate = {
        "key": "/works/OL26627585W",
        "title": "Red Rising",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2014,
        "edition_count": 8,
        "isbn": [],
    }
    respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": [duplicate, RED_RISING_DOC]})
    )
    work = await ol.resolve_by_title_author("Red Rising", "Pierce Brown")
    assert work is not None
    assert work.key == "OL17076473W"


@respx.mock
async def test_resolve_by_title_author_rejects_a_title_mismatch():
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [GOLDEN_SON_DOC]}))
    assert await ol.resolve_by_title_author("Red Rising", "Pierce Brown") is None


@respx.mock
async def test_resolve_by_title_author_rejects_an_author_mismatch():
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    assert await ol.resolve_by_title_author("Red Rising", "Someone Else") is None


@respx.mock
async def test_resolve_by_title_author_survives_a_timeout():
    respx.get(SEARCH_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert await ol.resolve_by_title_author("Red Rising", "Pierce Brown") is None


@respx.mock
async def test_resolve_by_isbns_survives_a_non_object_json_body():
    """An HTML error page proxied as JSON must not crash identity resolution."""
    respx.get(SEARCH_URL).mock(return_value=Response(200, json=[]))
    assert await ol.resolve_by_isbns(["9780345539809"]) == {}


@respx.mock
async def test_resolve_by_title_author_survives_a_non_object_json_body():
    respx.get(SEARCH_URL).mock(return_value=Response(200, json="nope"))
    assert await ol.resolve_by_title_author("Red Rising", "Pierce Brown") is None


SEARCH_DOCS = [
    {
        "key": "/works/OL17076473W",
        "title": "Red Rising",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2014,
        "edition_count": 26,
        "isbn": ["9780345539809"],
        "cover_i": 7316188,
        "readinglog_count": 1036,
        "ratings_count": 102,
        "subject": ["franchise:Red Rising", "genre:science fiction", "Dystopia"],
    },
    {
        "key": "/works/OL19726995W",
        "title": "Iron Gold",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2018,
        "edition_count": 14,
        "cover_i": 14511722,
        "readinglog_count": 114,
        "subject": ["franchise:Red Rising", "series:Red Rising Saga"],
    },
]


@respx.mock
async def test_search_works_maps_covers_popularity_and_subjects():
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": SEARCH_DOCS}))
    works = await ol.search_works("red rising")
    assert [w.key for w in works] == ["OL17076473W", "OL19726995W"]
    first = works[0]
    assert first.cover_id == 7316188
    assert first.readinglog_count == 1036
    assert first.ratings_count == 102
    assert "genre:science fiction" in first.subjects


@respx.mock
async def test_search_works_preserves_open_library_relevance_order():
    # Ranking is Open Library's job on ingest; we must not re-sort here.
    respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": list(reversed(SEARCH_DOCS))})
    )
    works = await ol.search_works("red rising")
    assert [w.key for w in works] == ["OL19726995W", "OL17076473W"]


@respx.mock
async def test_search_works_returns_empty_on_upstream_failure():
    # The never-raise contract: a search must still succeed when OL is down.
    respx.get(SEARCH_URL).mock(return_value=Response(503))
    assert await ol.search_works("red rising") == []


@respx.mock
async def test_search_works_returns_empty_on_timeout():
    # A cold search blocks a real person, so it gives up at _SEARCH_TIMEOUT
    # and lets the caller fall back rather than waiting out a 12s spike.
    respx.get(SEARCH_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert await ol.search_works("red rising") == []


@respx.mock
async def test_search_works_uses_the_shorter_search_timeout():
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": SEARCH_DOCS}))
    assert ol._SEARCH_TIMEOUT < ol._TIMEOUT
    assert await ol.search_works("red rising")


@respx.mock
async def test_search_works_skips_docs_with_no_key_or_title():
    respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": [{"title": "No Key"}, SEARCH_DOCS[0]]})
    )
    works = await ol.search_works("red rising")
    assert [w.key for w in works] == ["OL17076473W"]


@respx.mock
async def test_search_works_defaults_missing_counts_to_zero():
    doc = {"key": "/works/OL1W", "title": "Bare", "author_name": ["X"]}
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [doc]}))
    work = (await ol.search_works("bare"))[0]
    assert work.readinglog_count == 0
    assert work.ratings_count == 0
    assert work.cover_id is None
    assert work.subjects == ()


def test_cover_url_builds_an_open_library_url():
    assert ol.cover_url(7316188) == "https://covers.openlibrary.org/b/id/7316188-L.jpg"
    assert ol.cover_url(None) is None


def test_genre_slug_prefers_an_explicit_genre_tag():
    assert ol.genre_slug(["Fiction", "genre:science fiction"]) == "science-fiction"


def test_genre_slug_falls_back_to_a_plain_subject():
    assert ol.genre_slug(["Fantasy", "Dragons"]) == "fantasy"


def test_genre_slug_returns_none_when_nothing_matches():
    assert ol.genre_slug(["Dragons", "Swords"]) is None
