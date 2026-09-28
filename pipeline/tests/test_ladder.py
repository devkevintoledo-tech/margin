from pipeline.group.ladder import count_tags, parse_ordinal, rung1, rung2, rung3, rung4
from pipeline.group.types import Candidate, GWork, WdMembership, WdSeries


def gw(ol_id="OL1W", titles=("A Book",), subjects=None, editions=(), wd=()):
    return GWork(ol_id, tuple(titles), "OL1A", "single", subjects, tuple(tuple(e) for e in editions), frozenset(wd))


def test_ordinals():
    assert parse_ordinal("3") == 3.0
    assert parse_ordinal("2.5") == 2.5
    assert parse_ordinal("1a") is None
    assert parse_ordinal(None) is None


def test_rung1_reads_every_wikidata_series_with_its_ordinal():
    by_item = {"Q1": [WdMembership("Q1", "Q45875", "3"), WdMembership("Q1", "Q99", None)]}
    series = {"Q45875": WdSeries("Q45875", "A Song of Ice and Fire")}
    assert rung1(gw(wd=["Q1"]), by_item, series) == [
        Candidate("wd:Q45875", "A Song of Ice and Fire", 3.0, 1),
        Candidate("wd:Q99", "Q99", None, 1),
    ]


def test_rung2_prefers_the_franchise_then_the_broadest_series_tag():
    works = [gw("OL1W", subjects="series:Red Rising Trilogy\nseries:Red Rising Saga"),
             gw("OL2W", subjects="series:Red Rising Saga")]
    counts = count_tags(works)
    assert rung2(works[0], counts) == Candidate("ol:red rising saga", "Red Rising Saga", None, 2)
    assert rung2(gw(subjects="franchise:Red Rising\nseries:X"), counts).key == "ol:red rising"
    assert rung2(gw(subjects="fiction"), counts) is None


def test_rung3_is_a_majority_vote_across_editions():
    work = gw(editions=[["Red Rising Saga ; 5"], ["Red Rising Saga, #5"], ["Red Rising ; 4"], []])
    assert rung3(work) == Candidate("ol:red rising saga", "Red Rising Saga", 5.0, 3)


def test_rung3_counts_one_vote_per_edition():
    work = gw(editions=[["X ; 1", "X (1)"], ["Y ; 2"]])
    assert rung3(work).key == "ol:x"


def test_rung4_reads_titles():
    work = gw(titles=["The Dark Forest", "The Dark Forest (Remembrance of Earth's Past Series Book 2)"])
    assert rung4(work) == Candidate("ol:remembrance of earth s past", "Remembrance of Earth's Past", 2.0, 4)
    assert rung4(gw(titles=["The Hobbit"])) is None
