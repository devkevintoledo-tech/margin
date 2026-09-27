from pipeline.ids import assign_slugs, row_id, series_identity, work_identity


def test_row_ids_are_stable_across_runs_and_machines():
    # Literal on purpose: if this changes, every release id changes with it.
    assert row_id(work_identity("OL27448W")) == "24be4984-41f0-5f91-a993-a720b03ad937"
    assert row_id(series_identity("wd:Q45875")) == "0d206ae4-ee28-5ecc-957d-0d1aaca7e028"


def test_distinct_identities_get_distinct_ids():
    assert row_id("work:ol:OL1W") != row_id("edition:ol:OL1W")


def test_slugs_break_collisions_by_identity_order():
    slugs = assign_slugs({"series:single:OL9W": "Dune", "series:single:OL1W": "Dune", "series:wd:Q1": "Dune"})
    assert slugs == {"series:single:OL1W": "dune", "series:single:OL9W": "dune-2", "series:wd:Q1": "dune-3"}


def test_a_suffix_never_takes_another_names_base():
    slugs = assign_slugs({"a": "Dune", "b": "Dune", "c": "Dune 2"})
    assert slugs == {"a": "dune", "b": "dune-3", "c": "dune-2"}


def test_slugs_do_not_depend_on_input_order():
    names = {"x": "Red Rising", "y": "Red Rising", "z": "Golden Son"}
    assert assign_slugs(names) == assign_slugs(dict(reversed(list(names.items()))))
