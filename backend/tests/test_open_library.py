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
