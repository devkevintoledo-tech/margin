from pipeline.group.duplicates import DupWork, find_duplicates


def dup(ol_id, title="red rising", author="OL4A", wd=(), editions=("red rising",), pop=10, kind="single"):
    return DupWork(ol_id, author, title, kind, frozenset(wd), frozenset(editions), pop)


def test_same_author_cluster_and_title_merge_into_the_more_popular():
    assert find_duplicates([dup("OL30W", pop=900), dup("OL36W", pop=3)]) == {"OL36W": "OL30W"}


def test_a_wikidata_linked_work_survives_over_a_more_popular_one():
    assert find_duplicates([dup("OL30W", pop=900), dup("OL36W", wd=["Q1"], pop=3)]) == {"OL30W": "OL36W"}


def test_lower_ol_number_breaks_a_tie():
    assert find_duplicates([dup("OL100W"), dup("OL99W")]) == {"OL100W": "OL99W"}


def test_distinct_wikidata_items_are_different_books():
    assert find_duplicates([dup("OL1W", wd=["Q1"]), dup("OL2W", wd=["Q2"])]) == {}


def test_editions_with_no_shared_title_are_different_books():
    # Open Library titles three Brian Herbert books plain "Dune".
    works = [
        dup("OL1W", "dune", "OL9A", editions=["house atreides"]),
        dup("OL2W", "dune", "OL9A", editions=["house harkonnen"]),
        dup("OL3W", "dune", "OL9A", editions=["house corrino"]),
    ]
    assert find_duplicates(works) == {}


def test_a_work_without_editions_can_merge():
    assert find_duplicates([dup("OL1W", pop=5), dup("OL2W", editions=(), pop=1)]) == {"OL2W": "OL1W"}


def test_collections_never_merge():
    assert find_duplicates([dup("OL1W", kind="collection"), dup("OL2W", kind="collection")]) == {}


def test_different_author_clusters_never_merge():
    assert find_duplicates([dup("OL1W", author="OL4A"), dup("OL2W", author="OL5A")]) == {}


def test_edition_subtitles_tell_same_titled_books_apart():
    # The real records: every edition is titled plain "Dune"; only the subtitle differs.
    from pipeline.group.duplicates import edition_title_key

    works = [
        dup("OL1W", "dune", "OL9A", editions=[edition_title_key("Dune", "House Atreides")]),
        dup("OL2W", "dune", "OL9A", editions=[edition_title_key("Dune", "House Harkonnen")]),
    ]
    assert find_duplicates(works) == {}
    assert edition_title_key("Red Rising", None) == "red rising"
