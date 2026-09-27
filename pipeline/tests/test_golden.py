import pytest

from pipeline.golden import GoldenGateError, GoldenResult, GoldenSeries, MemberRow, evaluate, gate, reading_order


def row(work, position=None, year=None, title="t"):
    return MemberRow(work, position, year, title)


MEMBERS = {
    "ol:red rising": [row("OL34W", 5.0, 2015), row("OL30W", 1.0, 2014), row("OL31W", 2.0, 2015)],
    "wd:Q1": [row("OL60W", None, 1954, "The Fellowship of the Ring"), row("OL62W", None, 1955, "The Return")],
}


def test_reading_order_is_position_then_year_then_title():
    assert reading_order(MEMBERS["ol:red rising"]) == ["OL30W", "OL31W", "OL34W"]
    assert reading_order([row("B", None, 2000, "b"), row("A", None, 2000, "a"), row("C", 1.0, 2020)]) == ["C", "A", "B"]


def test_exact_membership_and_order_pass():
    result = evaluate([GoldenSeries("Red Rising", ("OL30W", "OL31W", "OL34W"))], MEMBERS)
    assert (result.membership_ok, result.order_ok, result.failures) == (1, 1, [])


def test_missing_members_and_wrong_order_are_reported():
    result = evaluate([GoldenSeries("RR", ("OL30W", "OL31W", "OL33W", "OL34W")),
                       GoldenSeries("LOTR", ("OL62W", "OL60W"))], MEMBERS)
    assert result.membership_ok == 1 and result.order_ok == 0
    assert "missing ['OL33W']" in result.failures[0]
    assert "order" in result.failures[1]


def test_merged_ids_resolve_through_aliases():
    aliases = {"OL36W": "OL30W"}
    result = evaluate([GoldenSeries("RR", ("OL36W", "OL31W", "OL34W"))], MEMBERS,
                      resolve=lambda w: aliases.get(w, w))
    assert (result.membership_ok, result.order_ok) == (1, 1)


def test_a_series_nobody_landed_in_fails():
    result = evaluate([GoldenSeries("Dune", ("OL1W",))], MEMBERS)
    assert result.failures == ["Dune: none of its works is in any series"]


def test_gate_thresholds():
    gate(GoldenResult(total=20, membership_ok=19, order_ok=19))
    with pytest.raises(GoldenGateError, match="membership 90.0%"):
        gate(GoldenResult(total=10, membership_ok=9, order_ok=10))
    with pytest.raises(GoldenGateError, match="empty"):
        gate(GoldenResult())


def test_draft_lists_wikidata_members_in_ordinal_order(world_ctx):
    from pipeline.golden import draft_from_wikidata
    from pipeline.stages import extract, fetch, select

    for stage in (fetch, select, extract):
        stage.run(world_ctx)
    draft = draft_from_wikidata(world_ctx.con, "Q45875")
    assert draft.splitlines()[0] == "- name: 'A Song of Ice and Fire'"
    members = [line.split("#")[0].strip(" -") for line in draft.splitlines() if line.startswith("    - ")]
    assert members == ["OL10W", "OL11W", "OL12W"]
    assert "verified_by: ''" in draft
