import pytest

from pipeline.group.decide import Decision
from pipeline.group.types import Membership
from pipeline.overrides import (
    MergeWorks, OverrideError, RejectSeries, RenameSeries, SetSeries, SplitWork,
    apply_identity, apply_series, load_overrides, series_rejects,
)


def write(tmp_path, text, name="a.yaml"):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_loads_every_override_kind(tmp_path):
    ops = load_overrides(write(tmp_path, """
- merge_works: [OL123W, OL456W]
- split_work: {work: OL789W, editions: [OL1M, OL2M]}
- set_series: {work: OL27448W, series: "wd:Q45875", position: 3}
- remove_from_series: {work: OL27448W, series: "ol:dune"}
- reject_series: "ol:Penguin Classics"
- rename_series: {series: "wd:Q45875", name: "A Song of Ice and Fire"}
"""))
    assert ops[0] == MergeWorks("OL123W", ("OL456W",))
    assert ops[2] == SetSeries("OL27448W", "wd:Q45875", 3.0, None)
    assert ops[4] == RejectSeries("ol:penguin classics")
    assert ops[5] == RenameSeries("wd:Q45875", "A Song of Ice and Fire")


@pytest.mark.parametrize("text,message", [
    ("- frobnicate: OL1W", "unknown override"),
    ("- merge_works: [OL1W]", "at least two"),
    ("- set_series: {work: OL1W}", "malformed"),
    ("- reject_series: penguin", "series must be"),
    ("merge_works: [OL1W, OL2W]", "expected a list"),
])
def test_malformed_entries_fail_with_their_location(tmp_path, text, message):
    with pytest.raises(OverrideError, match=message):
        load_overrides(write(tmp_path, text))


def test_merge_and_split_apply_to_identity():
    plan = apply_identity(
        [MergeWorks("OL1W", ("OL2W",)), SplitWork("OL3W", ("OL9M",))],
        works={"OL1W", "OL2W", "OL3W"},
        edition_work={"OL8M": "OL2W", "OL9M": "OL3W", "OL7M": "OL3W"},
        aliases={},
    )
    assert plan.aliases == {"OL2W": "OL1W"}
    assert plan.edition_work == {"OL8M": "OL1W", "OL9M": "OL3W~OL9M", "OL7M": "OL3W"}


def test_merge_follows_existing_duplicate_aliases():
    plan = apply_identity([MergeWorks("OL5W", ("OL1W",))], {"OL1W", "OL2W", "OL5W"}, {}, aliases={"OL2W": "OL1W"})
    assert plan.aliases == {"OL1W": "OL5W", "OL2W": "OL5W"}


def test_identity_overrides_reject_unknown_ids():
    with pytest.raises(OverrideError, match="unknown work OL404W"):
        apply_identity([MergeWorks("OL1W", ("OL404W",))], {"OL1W"}, {}, {})
    with pytest.raises(OverrideError, match="not an edition of"):
        apply_identity([SplitWork("OL1W", ("OL9M",))], {"OL1W"}, {"OL9M": "OL2W"}, {})


def decision():
    return Decision(memberships={"OL1W": {"ol:dune": Membership("ol:dune", 1.0, 2)}, "OL2W": {}},
                    names={"ol:dune": "Dune"}, rejected={}, decided_by={"OL1W": 2, "OL2W": None},
                    known_series={"ol:dune", "wd:Q45875"})


def test_set_series_wins_over_the_ladder():
    d = decision()
    apply_series([SetSeries("OL2W", "wd:Q45875", 3.0)], d, {"OL1W", "OL2W"})
    assert d.memberships["OL2W"] == {"wd:Q45875": Membership("wd:Q45875", 3.0, 0)}
    assert d.decided_by["OL2W"] == 0


def test_set_series_can_create_a_named_ol_series():
    d = decision()
    apply_series([SetSeries("OL2W", "ol:lord of the rings", 1.0, "The Lord of the Rings")], d, {"OL1W", "OL2W"})
    assert d.names["ol:lord of the rings"] == "The Lord of the Rings"


def test_series_overrides_reject_unknown_series():
    with pytest.raises(OverrideError, match="no series ol:nope"):
        apply_series([SetSeries("OL2W", "ol:nope")], decision(), {"OL1W", "OL2W"})
    with pytest.raises(OverrideError, match="no series"):
        apply_series([RejectSeries("ol:nope")], decision(), {"OL1W"})


def test_rename_and_rejects():
    d = decision()
    apply_series([RenameSeries("ol:dune", "Dune Chronicles")], d, {"OL1W"})
    assert d.names["ol:dune"] == "Dune Chronicles"
    assert series_rejects([RejectSeries("ol:x"), RenameSeries("ol:dune", "y")]) == {"ol:x"}
