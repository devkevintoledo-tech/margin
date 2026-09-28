import pytest

from pipeline.parse.series_strings import SeriesRef, parse_series_string, parse_title_series


@pytest.mark.parametrize("raw,expected", [
    ("A Song of Ice and Fire ; 3", SeriesRef("A Song of Ice and Fire", 3.0)),
    ("Red Rising Saga, #2", SeriesRef("Red Rising Saga", 2.0)),
    ("The Expanse (5)", SeriesRef("The Expanse", 5.0)),
    ("Discworld, book 12", SeriesRef("Discworld", 12.0)),
    ("Discworld #12", SeriesRef("Discworld", 12.0)),
    ("Mistborn ; v. 2.5", SeriesRef("Mistborn", 2.5)),
    ("Wheel of time, bk. 4", SeriesRef("Wheel of time", 4.0)),
    ("Harry Potter ; 7.", SeriesRef("Harry Potter", 7.0)),
    ("Remembrance of Earth's Past, #3", SeriesRef("Remembrance of Earth's Past", 3.0)),
    ("Penguin classics", SeriesRef("Penguin classics", None)),
    ("1984", None),
    ("; 3", None),
    ("   ", None),
    (None, None),
])
def test_edition_series_strings(raw, expected):
    assert parse_series_string(raw) == expected


@pytest.mark.parametrize("title,expected", [
    ("The Dark Forest (Remembrance of Earth's Past Series Book 2)", SeriesRef("Remembrance of Earth's Past", 2.0)),
    ("Golden Son (Red Rising Saga, #2)", SeriesRef("Red Rising Saga", 2.0)),
    ("The Two Towers (The Lord of the Rings, Part 2)", SeriesRef("The Lord of the Rings", 2.0)),
    ("Red Rising #1", SeriesRef("Red Rising", 1.0)),
    ("Death's End: Book 3 of the Remembrance of Earth's Past", SeriesRef("Remembrance of Earth's Past", 3.0)),
    ("Book 2 of 3", None),
    ("Catch-22", None),
    ("Fahrenheit 451", None),
    ("The Hobbit", None),
    ("Carrie (Signet Classics)", None),
])
def test_title_patterns(title, expected):
    assert parse_title_series(title) == expected
