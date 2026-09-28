from pipeline.group.guards import drop_adaptations, fold_map, imprint_rejections
from pipeline.group.types import Candidate, Membership, WdSeries


def c(key, rung, name="x", pos=None):
    return Candidate(key, name, pos, rung)


def test_a_series_spanning_four_author_clusters_is_an_imprint():
    cands = {f"OL{i}W": [c("ol:penguin classics", 2)] for i in range(4)}
    primary = {f"OL{i}W": f"OL{i}A" for i in range(4)}
    assert imprint_rejections(cands, primary) == {"ol:penguin classics": 4}


def test_three_author_clusters_is_still_a_series():
    cands = {f"OL{i}W": [c("ol:dune", 2)] for i in range(3)}
    assert imprint_rejections(cands, {f"OL{i}W": f"OL{i}A" for i in range(3)}) == {}


def test_blocklisted_names_are_rejected_regardless():
    assert imprint_rejections({"OL1W": [c("ol:a del rey book", 2)]}, {"OL1W": "OL1A"},
                              blocked=["ol:a del rey book"]) == {"ol:a del rey book": 1}


def test_wikidata_series_are_never_imprints():
    cands = {f"OL{i}W": [c("wd:Q1", 1)] for i in range(5)}
    assert imprint_rejections(cands, {f"OL{i}W": f"OL{i}A" for i in range(5)}) == {}


def test_folds_into_wikidata_by_name():
    cands = {"OL13W": [c("ol:a song of ice and fire", 3)]}
    wd = {"Q45875": WdSeries("Q45875", "A Song of Ice and Fire")}
    assert fold_map(cands, wd) == {"ol:a song of ice and fire": "wd:Q45875"}


def test_folds_into_wikidata_when_half_its_works_are_members():
    cands = {
        "OL1W": [c("wd:Q7", 1), c("ol:earthsea cycle", 2)],
        "OL2W": [c("ol:earthsea cycle", 2)],
    }
    assert fold_map(cands, {"Q7": WdSeries("Q7", "Earthsea")}) == {"ol:earthsea cycle": "wd:Q7"}


def test_does_not_fold_below_half():
    cands = {
        "OL1W": [c("wd:Q7", 1), c("ol:x", 2)],
        "OL2W": [c("ol:x", 2)],
        "OL3W": [c("ol:x", 2)],
    }
    assert fold_map(cands, {"Q7": WdSeries("Q7", "Other")}) == {}


def test_edition_series_folds_into_the_tag_its_siblings_carry():
    cands = {
        "OL30W": [c("ol:red rising", 2), c("ol:red rising saga", 3, pos=1.0)],
        "OL34W": [c("ol:red rising", 2), c("ol:red rising saga", 3, pos=5.0)],
    }
    assert fold_map(cands, {}) == {"ol:red rising saga": "ol:red rising"}


def test_rejected_series_never_fold():
    cands = {"OL1W": [c("ol:penguin classics", 2)]}
    wd = {"Q9": WdSeries("Q9", "Penguin Classics")}
    assert fold_map(cands, wd, rejected={"ol:penguin classics"}) == {}


def test_adaptations_by_another_author_are_dropped():
    memberships = {
        "OL30W": {"ol:red rising": Membership("ol:red rising", 1.0, 2)},
        "OL31W": {"ol:red rising": Membership("ol:red rising", 2.0, 2)},
        "OL35W": {"ol:red rising": Membership("ol:red rising", None, 2)},
    }
    drop_adaptations(memberships, {"OL30W": "OL4A", "OL31W": "OL4A", "OL35W": "OL6A"})
    assert memberships["OL35W"] == {}
    assert "ol:red rising" in memberships["OL30W"]


def test_wikidata_overrules_the_adaptation_filter():
    memberships = {
        "OL1W": {"wd:Q1": Membership("wd:Q1", 1.0, 1)},
        "OL2W": {"wd:Q1": Membership("wd:Q1", 2.0, 1)},
        "OL3W": {"wd:Q1": Membership("wd:Q1", 3.0, 1)},
    }
    drop_adaptations(memberships, {"OL1W": "OL1A", "OL2W": "OL1A", "OL3W": "OL9A"})
    assert "wd:Q1" in memberships["OL3W"]


def test_blocklisted_names_nobody_carries_are_not_reported():
    assert imprint_rejections({"OL1W": [c("ol:dune", 2)]}, {"OL1W": "OL1A"}, blocked=["ol:penguin classics"]) == {}


def test_companions_by_other_authors_do_not_make_a_series_an_imprint():
    # Four books by the author plus three companions by others: a series with
    # adaptations for drop_adaptations to remove, not a publisher line.
    cands = {f"OL{i}W": [c("ol:x", 2)] for i in range(7)}
    primary = {**{f"OL{i}W": "OL1A" for i in range(4)}, "OL4W": "OL2A", "OL5W": "OL3A", "OL6W": "OL4A"}
    assert imprint_rejections(cands, primary) == {}
