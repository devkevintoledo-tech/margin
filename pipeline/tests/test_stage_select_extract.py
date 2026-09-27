import pytest

from pipeline.stages import extract, fetch, select
from pipeline.stages.extract import AuthorRow, extract_work


@pytest.fixture
def selected(world_ctx):
    fetch.run(world_ctx)
    select.run(world_ctx)
    return world_ctx


def test_select_keeps_english_read_works_and_names_each_drop(selected):
    con = selected.con
    kept = {w for (w,) in con.execute("SELECT ol_id FROM selected").fetchall()}
    drops = dict(con.execute("SELECT ol_id, rule FROM select_drops").fetchall())
    assert drops == {"OL40W": "calendar", "OL41W": "not_english", "OL42W": "short"}
    assert {"OL10W", "OL30W", "OL36W", "OL50W", "OL63W"} <= kept


def test_extract_normalises_works_editions_and_authors(selected):
    extract.run(selected)
    con = selected.con
    row = con.execute("SELECT title, author, author_ids, first_publish_year, readinglog_count, ratings_count, "
                      "edition_count, subjects FROM works WHERE ol_id = 'OL30W'").fetchone()
    assert row == ("Red Rising", "Pierce Brown", ["OL4A"], 2014, 5, 2, 1, "franchise:Red Rising")
    assert con.execute("SELECT count(*) FROM editions WHERE work_ol_id = 'OL10W'").fetchone() == (1,)  # French one left out
    assert con.execute("SELECT series FROM editions WHERE ol_id = 'OL340M'").fetchone() == (["Red Rising Saga ; 5"],)
    assert con.execute("SELECT alternate_names FROM authors WHERE ol_id = 'OL2A'").fetchone() == (["Liu Cixin", "刘慈欣"],)


def test_extract_work_rules():
    authors = {"OL2A": AuthorRow("Cixin Liu", (), None)}
    record = {"title": "The Three-Body Problem (Deluxe Edition)", "authors": [{"key": "/authors/OL9A"}],
              "subjects": ["series:Remembrance of Earth's Past", "Fiction"], "covers": [-1, 42]}
    work = extract_work("OL20W", record, authors, resolve_author={"OL9A": "OL2A"}.get, edition_years=[2014, 2008])
    assert work["title"] == "The Three-Body Problem"
    assert work["raw_title"] == "The Three-Body Problem (Deluxe Edition)"
    assert work["author_ids"] == ["OL2A"]
    assert work["first_publish_year"] == 2008
    assert work["subjects"] == "series:Remembrance of Earth's Past\nFiction"
    assert work["cover_id"] == 42
    assert work["canonical_key"] == "the three body problem\x1fcixin liu"


def test_extract_work_without_known_authors():
    work = extract_work("OL1W", {"title": "Box Set: Books 1-3"}, {})
    assert work["author"] == "Unknown"
    assert work["kind"] == "collection"
