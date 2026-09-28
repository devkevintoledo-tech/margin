import pytest

from pipeline.stages import extract, fetch, group, select
from pipeline.stages.group import representative


@pytest.fixture
def grouped(world_ctx):
    for stage in (fetch, select, extract, group):
        stage.run(world_ctx)
    return world_ctx


def members(con, key):
    return con.execute("SELECT work_ol_id, position FROM g_members WHERE series_key = ? ORDER BY position, work_ol_id",
                       [key]).fetchall()


def room(con, ol):
    return con.execute("SELECT room FROM g_works WHERE ol_id = ?", [ol]).fetchone()[0]


def test_wikidata_series_gains_its_edition_string_member(grouped):
    assert members(grouped.con, "wd:Q45875") == [("OL10W", 1.0), ("OL11W", 2.0), ("OL12W", 3.0), ("OL13W", 4.0)]


def test_one_series_across_two_author_spellings(grouped):
    key = "ol:remembrance of earth s past"
    assert members(grouped.con, key) == [("OL20W", 1.0), ("OL21W", 2.0), ("OL22W", 3.0)]


def test_red_rising_is_ordered_merged_and_keeps_adaptations_out(grouped):
    con = grouped.con
    assert members(con, "ol:red rising") == [("OL30W", 1.0), ("OL31W", 2.0), ("OL32W", 3.0), ("OL33W", 4.0), ("OL34W", 5.0)]
    assert room(con, "OL35W") == "single:OL35W"
    aliases = dict(con.execute("SELECT ol_id, work_ol_id FROM g_aliases").fetchall())
    assert aliases == {"OL36W": "OL30W", "OL99W": "OL30W"}
    assert con.execute("SELECT count(*) FROM g_works WHERE ol_id = 'OL36W'").fetchone() == (0,)
    assert con.execute("SELECT readinglog_count FROM g_works WHERE ol_id = 'OL30W'").fetchone() == (6,)


def test_imprints_are_rejected(grouped):
    con = grouped.con
    assert con.execute("SELECT key, author_clusters FROM g_imprints").fetchall() == [("ol:penguin classics", 4)]
    assert room(con, "OL50W") == "single:OL50W"


def test_a_thin_universe_is_not_a_room(grouped):
    con = grouped.con
    assert {room(con, w) for w in ("OL60W", "OL61W", "OL62W")} == {"wd:Q15228"}
    assert con.execute("SELECT parent_key FROM g_series WHERE key = 'wd:Q15228'").fetchone() == (None,)
    assert con.execute("SELECT count(*) FROM g_series WHERE key = 'wd:Q81'").fetchone() == (0,)


def test_every_work_has_a_room_and_every_room_a_series(grouped):
    con = grouped.con
    orphans = con.execute("SELECT count(*) FROM g_works w LEFT JOIN g_series s ON s.key = w.room "
                          "WHERE s.key IS NULL").fetchone()
    assert orphans == (0,)


def test_an_override_moves_a_book_and_survives_the_rerun(grouped):
    (grouped.overrides_dir / "fixes.yaml").write_text(
        '- set_series: {work: OL63W, series: "wd:Q15228", position: 0}\n', encoding="utf-8")
    group.run(grouped)
    assert room(grouped.con, "OL63W") == "wd:Q15228"
    assert members(grouped.con, "wd:Q15228")[0] == ("OL63W", 0.0)


def test_representative_prefers_the_curated_cover():
    editions = [
        {"ol_id": "OL1M", "cover_id": 5, "isbn_13": "x", "page_count": 1},
        {"ol_id": "OL2M", "cover_id": 9, "isbn_13": None, "page_count": None},
        {"ol_id": "OL3M", "cover_id": None, "isbn_13": "x", "page_count": 1},
    ]
    assert representative(editions, work_cover=9) == "OL2M"
    assert representative(editions, work_cover=None) == "OL1M"
    assert representative([], None) is None
