from pipeline.group.decide import decide
from pipeline.group.types import GWork, Membership, WdMembership, WdSeries


def gw(ol_id, author="OL1A", titles=None, subjects=None, editions=(), wd=(), kind="single"):
    return GWork(ol_id, tuple(titles or [ol_id]), author, kind, subjects,
                 tuple(tuple(e) for e in editions), frozenset(wd))


ASOIAF = {"Q45875": WdSeries("Q45875", "A Song of Ice and Fire")}
ASOIAF_MEMBERS = [WdMembership("Q1", "Q45875", "1"), WdMembership("Q2", "Q45875", "2")]


def test_wikidata_wins_and_edition_strings_fill_in_missing_members():
    works = [gw("OL10W", wd=["Q1"]), gw("OL11W", wd=["Q2"]),
             gw("OL13W", editions=[["A Song of Ice and Fire ; 4"]])]
    d = decide(works, ASOIAF_MEMBERS, ASOIAF)
    assert d.memberships["OL10W"] == {"wd:Q45875": Membership("wd:Q45875", 1.0, 1)}
    assert d.memberships["OL13W"] == {"wd:Q45875": Membership("wd:Q45875", 4.0, 3)}
    assert d.decided_by == {"OL10W": 1, "OL11W": 1, "OL13W": 3}
    assert d.names["wd:Q45875"] == "A Song of Ice and Fire"


def test_position_comes_from_the_highest_rung_that_has_one():
    works = [gw("OL1W", wd=["Q3"], editions=[["A Song of Ice and Fire ; 3"]])]
    d = decide(works, [WdMembership("Q3", "Q45875", None)], ASOIAF)
    assert d.memberships["OL1W"]["wd:Q45875"].position == 3.0


def test_imprint_members_become_singletons():
    works = [gw(f"OL5{i}W", author=f"OL{i}A", subjects="series:Penguin Classics") for i in range(4)]
    d = decide(works, [], {})
    assert all(ms == {} for ms in d.memberships.values())
    assert d.rejected == {"ol:penguin classics": 4}


def test_override_rejects_act_like_imprints():
    d = decide([gw("OL1W", subjects="series:Dune")], [], {}, rejects={"ol:dune"})
    assert d.memberships["OL1W"] == {}


def test_collections_join_without_a_position():
    works = [gw("OL1W", editions=[["Mistborn ; 1"]]), gw("OL2W", editions=[["Mistborn ; 2"]]),
             gw("OL9W", kind="collection", editions=[["Mistborn ; 1-3"], ["Mistborn ; 1"]])]
    d = decide(works, [], {})
    assert d.memberships["OL9W"] == {"ol:mistborn": Membership("ol:mistborn", None, 3)}


def test_a_lone_title_pattern_is_not_a_series():
    d = decide([gw("OL1W", titles=["Red Rising #1"])], [], {})
    assert d.memberships["OL1W"] == {}
    assert d.decided_by["OL1W"] is None


def test_red_rising_positions_fix_publication_order():
    works = [
        gw("OL30W", subjects="franchise:Red Rising", editions=[["Red Rising Saga ; 1"]]),
        gw("OL34W", subjects="franchise:Red Rising", editions=[["Red Rising Saga ; 5"]]),
        gw("OL35W", author="OL6A", subjects="franchise:Red Rising"),
    ]
    d = decide(works, [], {})
    assert d.memberships["OL34W"] == {"ol:red rising": Membership("ol:red rising", 5.0, 2)}
    assert d.memberships["OL35W"] == {}
