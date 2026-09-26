"""Series detection is pure string work over Open Library subject tags."""

import pytest

from app.services.series_identity import (
    SeriesTags,
    choose_container,
    join_subjects,
    parse_tags,
    series_key,
    slugify,
    tag_external_id,
    tag_name,
)

RED_RISING = join_subjects(
    [
        "Science fiction",
        "franchise:Red Rising",
        "series:Red Rising Trilogy",
        "series:Red Rising Saga",
        "form:novel",
    ]
)


def test_join_subjects_keeps_tag_boundaries():
    assert join_subjects(["a b", "series:X Y"]) == "a b\nseries:X Y"
    assert join_subjects([]) is None


def test_parse_tags_reads_franchise_and_series_lines():
    assert parse_tags(RED_RISING) == SeriesTags(
        franchises=("franchise:Red Rising",),
        series=("series:Red Rising Trilogy", "series:Red Rising Saga"),
    )


@pytest.mark.parametrize(
    "subjects, expected",
    [
        (None, SeriesTags((), ())),
        ("", SeriesTags((), ())),
        ("Fiction\nFantasy", SeriesTags((), ())),
        # Underscored and oddly spaced forms normalize to one tag.
        ("series:Red_Rising_Saga", SeriesTags((), ("series:Red Rising Saga",))),
        ("SERIES:  Mistborn  ", SeriesTags((), ("series:Mistborn",))),
        # Duplicates collapse, order preserved.
        ("series:A\nseries:A\nseries:B", SeriesTags((), ("series:A", "series:B"))),
        # Empty names are not tags.
        ("series:\nfranchise: ", SeriesTags((), ())),
        # A legacy space-joined blob is one line with several tags in it: a tag
        # name never contains ':', so the line is ignored rather than misread.
        (
            "franchise:Red Rising series:Red Rising Trilogy genre:science fiction",
            SeriesTags((), ()),
        ),
    ],
)
def test_parse_tags_table(subjects, expected):
    assert parse_tags(subjects) == expected


def test_franchise_wins_over_series():
    assert choose_container(parse_tags(RED_RISING), {}) == "franchise:Red Rising"


def test_several_franchises_pick_by_name():
    tags = SeriesTags(("franchise:Zeta", "franchise:Alpha"), ())
    assert choose_container(tags, {}) == "franchise:Alpha"


def test_broadest_series_wins_without_a_franchise():
    tags = SeriesTags((), ("series:Red Rising Trilogy", "series:Red Rising Saga"))
    counts = {"series:Red Rising Trilogy": 3, "series:Red Rising Saga": 6}
    assert choose_container(tags, counts) == "series:Red Rising Saga"


def test_series_tie_breaks_on_name():
    tags = SeriesTags((), ("series:Beta", "series:Alpha"))
    assert choose_container(tags, {"series:Beta": 2, "series:Alpha": 2}) == "series:Alpha"
    # Missing counts are zero, still a tie.
    assert choose_container(tags, {}) == "series:Alpha"


def test_no_tags_means_no_container():
    assert choose_container(SeriesTags((), ()), {}) is None


def test_tag_name_and_external_id():
    assert tag_name("series:Red Rising Saga") == "Red Rising Saga"
    assert tag_external_id("series:Red Rising Saga") == "series:red rising saga"
    assert tag_external_id("franchise:Red  Rising!") == "franchise:red rising"


@pytest.mark.parametrize(
    "name, slug",
    [
        ("Red Rising", "red-rising"),
        ("The Hitchhiker's Guide to the Galaxy", "the-hitchhikers-guide-to-the-galaxy"),
        ("Café Society", "cafe-society"),
        ("  --Dune--  ", "dune"),
        ("Кровь", "series"),  # nothing ASCII survives: never an empty slug
        ("", "series"),
    ],
)
def test_slugify_table(name, slug):
    assert slugify(name) == slug


def test_slugify_caps_length_on_a_word_boundary():
    got = slugify("word " * 40, max_length=12)
    assert got == "word-word"
    assert len(got) <= 12


def test_series_key_normalizes():
    assert series_key("The Red-Rising  Saga!") == "the red rising saga"
