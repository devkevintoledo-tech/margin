import pytest

from pipeline.config import PIPELINE_DIR
from pipeline.select_rules import JunkRules, WorkForSelect

RULES = JunkRules.load(PIPELINE_DIR / "rules" / "junk.yaml")


def work(title="A Book", subjects=(), authors=("OL1A",), max_pages=300, publishers=()):
    return WorkForSelect("OL1W", title, tuple(subjects), tuple(authors), max_pages, tuple(publishers))


# Real books whose titles brush against a junk pattern. Every rule change must keep them.
KEEP = [
    work("The Diary of a Young Girl"),
    work("Diary of a Wimpy Kid"),
    work("A Journal of the Plague Year"),
    work("The Colour of Magic"),
    work("A Dissertation upon Roast Pig"),
    work("The Summer Book"),
    work("Analysis"),
]


@pytest.mark.parametrize("keep", KEEP, ids=[w.title for w in KEEP])
def test_real_books_are_kept(keep):
    assert RULES.reason(keep) is None


@pytest.mark.parametrize("candidate,reason", [
    (work(authors=()), "no_author"),
    (work(max_pages=24), "short"),
    (work("Red Rising 2027 Wall Calendar"), "calendar"),
    (work("2026 Diary"), "calendar"),
    (work("Blank", subjects=["Calendars"]), "calendar"),
    (work("The Hobbit Colouring Book"), "colouring_book"),
    (work("Stellar Winds", subjects=["Dissertations, Academic"]), "thesis"),
    (work("Annual Report", publishers=["U.S. Government Printing Office"]), "government_document"),
    (work("Summary of Atomic Habits"), "study_guide"),
    (work("Analysis of The Great Gatsby"), "study_guide"),
    (work("The Great Gatsby Study Guide"), "study_guide"),
    (work("Macbeth", subjects=["Study guides"]), "study_guide"),
])
def test_junk_is_dropped_with_its_rule(candidate, reason):
    assert RULES.reason(candidate) == reason


def test_unknown_page_count_is_kept():
    assert RULES.reason(work(max_pages=None)) is None
