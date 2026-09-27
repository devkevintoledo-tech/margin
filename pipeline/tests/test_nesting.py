from pipeline.group.nesting import rooms


def test_a_parent_with_two_child_series_is_the_room():
    memberships = {"OL1W": ["wd:MISTBORN"], "OL2W": ["wd:MISTBORN"], "OL3W": ["wd:STORMLIGHT"]}
    parents = {"wd:MISTBORN": "wd:COSMERE", "wd:STORMLIGHT": "wd:COSMERE"}
    room, parent_of = rooms(memberships, parents)
    assert room == {"OL1W": "wd:COSMERE", "OL2W": "wd:COSMERE", "OL3W": "wd:COSMERE"}
    assert parent_of == {"wd:COSMERE": None, "wd:MISTBORN": "wd:COSMERE", "wd:STORMLIGHT": "wd:COSMERE"}


def test_a_universe_with_one_child_does_not_swallow_it():
    memberships = {"OL60W": ["wd:LOTR"], "OL61W": ["wd:LOTR"], "OL62W": ["wd:LOTR"]}
    room, parent_of = rooms(memberships, {"wd:LOTR": "wd:MIDDLE_EARTH"})
    assert set(room.values()) == {"wd:LOTR"}
    assert parent_of == {"wd:LOTR": None}


def test_a_parent_with_two_direct_works_is_a_room():
    memberships = {"OL1W": ["wd:DISCWORLD"], "OL2W": ["wd:DISCWORLD"], "OL3W": ["wd:RINCEWIND"]}
    room, _ = rooms(memberships, {"wd:RINCEWIND": "wd:DISCWORLD"})
    assert room["OL3W"] == "wd:DISCWORLD"


def test_a_work_in_two_trees_takes_the_bigger_room():
    memberships = {"OL1W": ["wd:A", "wd:B"], "OL2W": ["wd:A"], "OL3W": ["wd:A"]}
    room, _ = rooms(memberships, {})
    assert room["OL1W"] == "wd:A"


def test_parent_cycles_terminate():
    memberships = {"OL1W": ["wd:A"], "OL2W": ["wd:A"], "OL3W": ["wd:B"], "OL4W": ["wd:B"]}
    room, _ = rooms(memberships, {"wd:A": "wd:B", "wd:B": "wd:A"})
    assert set(room) == {"OL1W", "OL2W", "OL3W", "OL4W"}


def test_works_without_series_have_no_room():
    room, parent_of = rooms({"OL1W": []}, {})
    assert room == {} and parent_of == {}
