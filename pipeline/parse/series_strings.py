"""Series evidence written as text: edition ``series`` fields and titles.

Pure string rules, tested as tables. Two sources, one result type:

* an Open Library edition's ``series`` field — ``Name ; 2``, ``Name, #2``,
  ``Name (2)``, ``Name, book 2``, or a bare name with no position (ladder rung 3);
* a title that carries its series — ``(X Series Book 2)``, ``X #2``,
  ``Book 2 of X`` (rung 4).
"""

from __future__ import annotations

import re
from typing import NamedTuple


class SeriesRef(NamedTuple):
    name: str
    position: float | None


_POS = r"(?P<pos>\d{1,3}(?:\.\d{1,2})?)"
_MARK = r"(?:#|no\.?|v\.|vol\.?|volume|book|bk\.?|part)"
_SERIES_FORMS = (
    re.compile(rf"^(?P<name>.+?)\s*;\s*(?:{_MARK}\s*)?{_POS}$", re.I),
    re.compile(rf"^(?P<name>.+?),\s*{_MARK}\s*{_POS}$", re.I),
    re.compile(rf"^(?P<name>.+?)\s*\(\s*(?:{_MARK}\s*)?{_POS}\s*\)$", re.I),
    re.compile(rf"^(?P<name>.+?)\s+{_MARK}\s*{_POS}$", re.I),
)
_TITLE_FORMS = (
    re.compile(rf"\((?P<name>[^()]+?)(?:\s+series)?,?\s+{_MARK}\s*{_POS}\s*\)", re.I),
    re.compile(
        r"\b(?:book|volume|part)\s+(?P<pos>\d{1,3})\s+of\s+(?:the\s+)?"
        r"(?P<name>[^():]+?)(?:\s+series)?\s*\)?\s*$",
        re.I,
    ),
    re.compile(rf"^(?P<name>[^()#]+?)\s*#\s*{_POS}\s*$"),
)
_LETTER = re.compile(r"[^\W\d_]")
_SPACE = re.compile(r"\s+")


def _clean_name(raw: str) -> str | None:
    """A usable series name, or None. "Book 2 of 3" names nothing."""
    name = _SPACE.sub(" ", raw).strip(" ,;:-")
    if not _LETTER.search(name) or len(name) > 150:
        return None
    return name


def parse_series_string(raw: str | None) -> SeriesRef | None:
    text = _SPACE.sub(" ", raw or "").strip().rstrip(".").strip()
    if not text:
        return None
    for form in _SERIES_FORMS:
        match = form.match(text)
        if match:
            name = _clean_name(match.group("name"))
            return SeriesRef(name, float(match.group("pos"))) if name else None
    name = _clean_name(text)
    return SeriesRef(name, None) if name else None


def parse_title_series(title: str | None) -> SeriesRef | None:
    """Series named inside a title. A title without a position names none."""
    text = _SPACE.sub(" ", title or "").strip()
    for form in _TITLE_FORMS:
        match = form.search(text)
        if match:
            name = _clean_name(match.group("name"))
            if name:
                return SeriesRef(name, float(match.group("pos")))
    return None
