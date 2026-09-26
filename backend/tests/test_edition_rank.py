"""The edition ladder: which edition is allowed to speak for a work.

Pure — no DB, no flush. `Book` instances are constructed in memory, which is
why nothing here needs the `db_session` fixture.
"""

from app.models import Book
from app.services.works import edition_rank


def edition(**kw):
    base = dict(
        source="google_books",
        external_id="x",
        title="Red Rising",
        author="Pierce Brown",
    )
    base.update(kw)
    return Book(**base)


def test_english_beats_a_richer_translation():
    english = edition(language="en")
    german = edition(
        language="de",
        cover_url="https://x/de.jpg",
        description="Der fulminante Auftakt ...",
        isbn_13="9783453316355",
        page_count=560,
        ratings_count=900,
    )
    assert max([german, english], key=edition_rank) is english


def test_unknown_language_loses_to_english_and_beats_a_translation():
    english = edition(language="en")
    unknown = edition(language=None)
    german = edition(language="de")
    assert max([unknown, english], key=edition_rank) is english
    assert max([german, unknown], key=edition_rank) is unknown


def test_regional_english_counts_as_english():
    british = edition(language="en-GB")
    portuguese = edition(language="pt-BR", cover_url="https://x/pt.jpg")
    assert max([portuguese, british], key=edition_rank) is british


def test_within_a_language_a_cover_wins():
    plain = edition(language="en", description="A boy from the mines.")
    illustrated = edition(language="en", cover_url="https://x/en.jpg")
    assert max([plain, illustrated], key=edition_rank) is illustrated


def test_with_equal_covers_a_description_wins():
    bare = edition(language="en", cover_url="https://x/a.jpg")
    described = edition(
        language="en", cover_url="https://x/b.jpg", description="A boy."
    )
    assert max([bare, described], key=edition_rank) is described


def test_completeness_breaks_a_tie_within_a_tier():
    thin = edition(language="en", cover_url="https://x/a.jpg", description="A boy.")
    rich = edition(
        language="en",
        cover_url="https://x/b.jpg",
        description="A boy.",
        isbn_13="9780345539786",
        page_count=382,
        ratings_count=1200,
    )
    assert max([thin, rich], key=edition_rank) is rich


def test_an_empty_language_string_is_treated_as_unknown():
    blank = edition(language="")
    german = edition(language="de", cover_url="https://x/de.jpg")
    assert max([german, blank], key=edition_rank) is blank
