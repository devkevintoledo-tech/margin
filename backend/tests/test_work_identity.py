import pytest

from app.services import work_identity as wi


# ---------------------------------------------------------------------------
# clean_title() — the Tier 3 fallback's entire accuracy lives here.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Red Rising", "red rising"),
        ("Red Rising (Deluxe Slipcase Edition)", "red rising"),
        ("Red Rising [Hardcover]", "red rising"),
        ("Red Rising 01", "red rising"),
        ("Red Rising #1", "red rising"),
        ("Red Rising, Vol. 2", "red rising"),
        ("Red Rising Book 3", "red rising"),
        ("The Hobbit: Illustrated Edition", "the hobbit"),
        ("Dune: 50th Anniversary Edition", "dune"),
    ],
)
def test_clean_title_strips_edition_noise(raw, expected):
    assert wi.clean_title(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # A colon-separated subtitle is meaningful: this is a DIFFERENT work.
        ("Red Rising: Sons of Ares", "red rising sons of ares"),
        # A trailing number that is part of the title must survive. We only
        # strip a trailing volume number <= 20 that leaves >= 2 tokens behind.
        ("Fahrenheit 451", "fahrenheit 451"),
        ("Catch 22", "catch 22"),
        ("Slaughterhouse 5", "slaughterhouse 5"),
        ("1984", "1984"),
    ],
)
def test_clean_title_keeps_meaningful_text(raw, expected):
    assert wi.clean_title(raw) == expected


# ---------------------------------------------------------------------------
# canonical_key() / heuristic_external_id()
# ---------------------------------------------------------------------------

def test_canonical_key_uses_clean_title_and_first_author():
    key = wi.canonical_key("Red Rising (Deluxe Slipcase Edition)", "Pierce Brown, Tim Gerard Reynolds")
    assert key == "red rising\x1fpierce brown"


def test_canonical_key_matches_across_edition_variants():
    assert wi.canonical_key("Red Rising 01", "Pierce Brown") == wi.canonical_key(
        "Red Rising (Deluxe Slipcase Edition)", "Pierce Brown"
    )


def test_canonical_key_separates_different_works_by_the_same_author():
    assert wi.canonical_key("Red Rising", "Pierce Brown") != wi.canonical_key(
        "Red Rising: Sons of Ares", "Pierce Brown"
    )


def test_heuristic_external_id_is_stable_sha1():
    key = wi.canonical_key("Red Rising", "Pierce Brown")
    assert wi.heuristic_external_id(key) == wi.heuristic_external_id(key)
    assert len(wi.heuristic_external_id(key)) == 40


# ---------------------------------------------------------------------------
# normalize_isbn() — OL returns ISBN-10 and ISBN-13 mixed in one list.
# ---------------------------------------------------------------------------

def test_normalize_isbn_upgrades_isbn_10():
    # 0345539788 is an ISBN-10 for a Red Rising edition.
    assert wi.normalize_isbn("0345539788") == "9780345539786"


def test_normalize_isbn_passes_through_isbn_13_and_strips_separators():
    assert wi.normalize_isbn("978-0-345-53980-9") == "9780345539809"
    assert wi.normalize_isbn("9780345539809") == "9780345539809"


def test_normalize_isbn_rejects_junk():
    assert wi.normalize_isbn(None) is None
    assert wi.normalize_isbn("") is None
    assert wi.normalize_isbn("12345") is None


# ---------------------------------------------------------------------------
# classify_kind() — conservative on purpose.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title",
    [
        "Red Rising 3-Book Bundle",
        "Red Rising 1-6 ebook collection",
        "Pierce Brown's Red Rising: Sons of Ares Omnibus",
        "The Red Rising Series Collection 5 Books Set By Pierce Brown",
        "The Broken Earth Trilogy Box Set",
        "Dune Boxed Set: Books 1-6",
    ],
)
def test_classify_kind_flags_collections(title):
    assert wi.classify_kind(title) == "collection"


@pytest.mark.parametrize(
    "title",
    [
        "Red Rising",
        "Collected Fictions",       # bare "collected" must NOT match
        "The Complete Stories",     # bare "complete" must NOT match
        "Red Rising: Sons of Ares",
    ],
)
def test_classify_kind_leaves_single_works_alone(title):
    assert wi.classify_kind(title) == "single"


def test_classify_kind_reads_the_subtitle_too():
    assert wi.classify_kind("Red Rising", "The Complete Series") == "collection"
