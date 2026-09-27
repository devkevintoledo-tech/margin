from pipeline.db import table_names
from pipeline.stages import fetch


def rows(con, sql):
    return con.execute(sql).fetchall()


def test_fetch_loads_the_read_set_and_its_sources(world_ctx):
    fetch.run(world_ctx)
    con = world_ctx.con
    assert set(fetch.TABLES) <= table_names(con)
    works = {w for (w,) in rows(con, "SELECT ol_id FROM raw_works")}
    assert "OL70W" not in works  # nobody read it and Wikidata does not know it
    assert {"OL10W", "OL12W", "OL30W", "OL41W", "OL63W"} <= works
    # Two ratings under the redirected id count toward the survivor.
    assert rows(con, "SELECT ratings_count, readinglog_count FROM raw_popularity WHERE ol_id = 'OL30W'") == [(2, 5)]
    assert rows(con, "SELECT from_ol, to_ol FROM raw_work_aliases") == [("OL99W", "OL30W")]
    assert rows(con, "SELECT edition_count FROM raw_edition_counts WHERE ol_id = 'OL10W'") == [(2,)]
    authors = {a for (a,) in rows(con, "SELECT ol_id FROM raw_authors")}
    assert {"OL1A", "OL2A", "OL3A", "OL5A"} <= authors
    assert rows(con, "SELECT name FROM wd_author_names WHERE qid = 'Q5'") == [("刘慈欣",)]
    assert rows(con, "SELECT parents FROM wd_series WHERE qid = 'Q15228'") == [(["Q81"],)]
    assert sorted(n for (n,) in rows(con, "SELECT name FROM sources")) == [
        "authors", "editions", "ratings", "reading_log", "wikidata", "works"]


def test_fetch_never_writes_the_editions_dump(world_ctx):
    fetch.run(world_ctx)
    assert not any("editions" in p.name for p in world_ctx.raw_dir.iterdir())
