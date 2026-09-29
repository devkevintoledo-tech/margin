import pytest

from app.services.genre_inference import (
    Taxonomy, TaxonomyError, infer_genres, load_taxonomy, parse_taxonomy, shipped_taxonomy,
)

TAX = parse_taxonomy([
    {"slug": "fantasy", "name": "Fantasy", "match": ["fantasy"], "children": [
        {"slug": "epic-fantasy", "name": "Epic Fantasy", "match": ["epic fantasy", "fantasy epic"]},
        {"slug": "grimdark", "name": "Grimdark", "match": ["grimdark", "dark fantasy"]},
    ]},
    {"slug": "mystery", "name": "Mystery", "match": ["crime", "mystery"]},
    {"slug": "history", "name": "History", "match": ["history"], "exclude": ["fiction"]},
    {"slug": "literary-fiction", "name": "Literary Fiction", "match": ["literary fiction"]},
])


def test_explicit_genre_tags_win_over_plain_subjects():
    assert infer_genres(["genre:epic fantasy", "Crime"], TAX) == {"epic-fantasy", "fantasy"}


def test_plain_subjects_are_used_when_no_explicit_tag_matches():
    assert infer_genres(["genre:space western", "Fiction, fantasy, epic"], TAX) == {"fantasy", "epic-fantasy"}


def test_needles_match_whole_words_only():
    assert infer_genres(["Crimea", "Crimean War"], TAX) == set()


def test_matching_is_case_and_punctuation_insensitive():
    # "dark fantasy" also contains the word "fantasy": both fire.
    assert infer_genres(["DARK-FANTASY"], TAX) == {"grimdark", "fantasy"}


def test_every_match_is_kept():
    assert infer_genres(["Fantasy", "Crime"], TAX) == {"fantasy", "mystery"}


def test_plain_fiction_infers_nothing():
    assert infer_genres(["Fiction", "Novels"], TAX) == set()


def test_prefixed_non_genre_subjects_never_infer():
    # Review Focus 1: series:, place:, person:, nyt: tags name things, not genres.
    assert infer_genres(["series:Fantasy Masterworks", "place:Crime Alley", "nyt:mystery"], TAX) == set()


def test_exclude_keeps_a_subject_from_inferring_that_genre():
    assert infer_genres(["Great Britain -- History -- Fiction"], TAX) == set()
    assert infer_genres(["Great Britain -- History"], TAX) == {"history"}


def test_an_empty_match_list_is_vote_only():
    tax = parse_taxonomy([{"slug": "cozy", "name": "Cozy", "match": []}])
    assert infer_genres(["cozy"], tax) == set()


@pytest.mark.parametrize("data, message", [
    ([], "non-empty list"),
    ([{"slug": "a", "name": "A"}, {"slug": "a", "name": "B"}], "duplicate slug a"),
    ([{"slug": "a", "name": "A", "children": [
        {"slug": "b", "name": "B", "children": [{"slug": "c", "name": "C"}]}]}], "cannot have subgenres"),
    ([{"slug": "Not A Slug", "name": "A"}], "bad slug"),
    ([{"slug": "a", "name": ""}], "needs a name"),
    ([{"slug": "a", "name": "A", "colour": "red"}], "unknown keys"),
    ([{"slug": "a", "name": "A", "match": ["!!!"]}], "empty match phrase"),
])
def test_validation_rejects_bad_files(data, message):
    with pytest.raises(TaxonomyError, match=message):
        parse_taxonomy(data)


def test_positions_follow_file_order_among_siblings():
    by = TAX.by_slug()
    assert (by["fantasy"].position, by["mystery"].position) == (0, 1)
    assert (by["epic-fantasy"].position, by["grimdark"].position) == (0, 1)
    assert by["grimdark"].parent == "fantasy"


def test_the_shipped_file_loads_and_keeps_the_eight_original_parents():
    tax = load_taxonomy()
    parents = {e.slug for e in tax.entries if e.parent is None}
    assert {"literary-fiction", "science-fiction", "fantasy", "history", "philosophy",
            "biography", "mystery", "poetry"} <= parents
    assert shipped_taxonomy() is shipped_taxonomy()  # cached
