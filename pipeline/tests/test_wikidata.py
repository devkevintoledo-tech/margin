import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from pipeline.group.types import WdMembership, WdSeries
from pipeline.sources.wikidata import WikidataError, fetch_memberships, fetch_series
from pipeline.tests.fixtures.dumps import entity, sparql_json

URL = "https://sparql.test/sparql"


def query_of(request) -> str:
    return parse_qs(request.content.decode())["query"][0]


@respx.mock
def test_pages_until_a_short_page():
    rows = [{"item": entity(f"Q{i}"), "olid": f"OL{i}W", "series": entity("Q45875"), "ordinal": str(i)}
            for i in range(1, 6)]

    def serve(request):
        q = query_of(request)
        offset = int(q.rsplit("OFFSET", 1)[1])
        return httpx.Response(200, json=sparql_json(rows[offset:offset + 2]))

    route = respx.post(URL).mock(side_effect=serve)
    with httpx.Client() as client:
        found = fetch_memberships(client, URL, sleep=lambda s: None, page_size=2)
    assert route.call_count == 3
    assert found[0] == (WdMembership("Q1", "Q45875", "1"), "OL1W")
    assert len(found) == 5


@respx.mock
def test_a_page_that_keeps_failing_aborts():
    respx.post(URL).mock(return_value=httpx.Response(503))
    with httpx.Client() as client, pytest.raises(WikidataError):
        fetch_memberships(client, URL, sleep=lambda s: None)


@respx.mock
def test_series_details_climb_to_parents():
    def serve(request):
        q = query_of(request)
        if "wd:Q15228" in q:
            return httpx.Response(200, json=sparql_json([
                {"series": entity("Q15228"), "label": "The Lord of the Rings", "parent": entity("Q81")}]))
        return httpx.Response(200, json=sparql_json([{"series": entity("Q81"), "label": "Middle-earth"}]))

    respx.post(URL).mock(side_effect=serve)
    with httpx.Client() as client:
        series = fetch_series(client, URL, {"Q15228"}, sleep=lambda s: None)
    assert series == {
        "Q15228": WdSeries("Q15228", "The Lord of the Rings", (), ("Q81",)),
        "Q81": WdSeries("Q81", "Middle-earth", (), ()),
    }
