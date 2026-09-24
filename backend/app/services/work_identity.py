"""Pure identity helpers for grouping editions into works.

No IO, no ORM — everything here is a deterministic string function so the
grouping rules can be tested exhaustively and read in one sitting. The Open
Library client (``open_library.py``) and the resolution orchestration
(``works.py``) build on top of these.
"""

from __future__ import annotations

import hashlib
import re

from app.services.google_books import normalize

# A parenthetical or bracketed group is always edition packaging:
# "(Deluxe Slipcase Edition)", "[Hardcover]".
_BRACKETED = re.compile(r"[\(\[][^\)\]]*[\)\]]")

# A trailing segment introduced by ':' or ',' that is *only* edition words.
# "The Hobbit: Illustrated Edition" loses its tail; "Red Rising: Sons of Ares"
# keeps it, which is the distinction the whole heuristic tier rests on.
_EDITION_WORDS = (
    r"deluxe|slipcase|illustrated|anniversary|revised|reprint|unabridged|"
    r"abridged|annotated|movie tie[- ]?in|collector'?s|special|expanded|"
    r"international|\d+(st|nd|rd|th)"
)
_EDITION_TAIL = re.compile(
    rf"\s*[:,]\s*(?:the\s+)?(?:{_EDITION_WORDS})[\w\s'-]*?(?:edition|printing)?\s*$",
    re.IGNORECASE,
)

# Volume markers: "Red Rising 01", "#1", "Vol. 2", "Book 3", "Part 4".
_VOLUME_MARKER = re.compile(
    r"\s*(?:,\s*)?(?:#|vol\.?|volume|book|part)?\s*(\d{1,3})\s*$",
    re.IGNORECASE,
)
_VOLUME_WORD = re.compile(r"(?:#|vol\.?|volume|book|part)\s*\d{1,3}\s*$", re.IGNORECASE)

# Highest volume number we will treat as a series marker rather than as part of
# the title. "Fahrenheit 451" and "Catch 22" survive this bound.
_MAX_VOLUME_NUMBER = 20

_COLLECTION_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"\bbox(?:ed)? set\b",
        r"\bomnibus\b",
        r"\bbundle\b",
        r"\bcollection\b",
        r"\bcomplete series\b",
        r"\bbooks? \d+\s*[-–—]\s*\d+\b",
        r"\b\d+\s*[-–—]\s*book\b",
        r"\b\d+ books\b",
    )
)


def _strip_edition_noise(title: str) -> str:
    """Remove edition packaging, preserving the text otherwise.

    Deliberately does NOT drop everything after a colon — a subtitle usually
    names a different book (``Red Rising: Sons of Ares``). Only a colon-led
    tail made of edition words is dropped.
    """
    working = _BRACKETED.sub(" ", title)
    working = _EDITION_TAIL.sub("", working)
    return _strip_volume_marker(working)


def clean_title(title: str) -> str:
    """The grouping form of a title: edition packaging removed, then normalized.

    Lowercased and stripped of punctuation, so it is a key, not something to
    show a reader. Use :func:`display_title` for that.
    """
    if not title:
        return ""
    return normalize(_strip_edition_noise(title))


def display_title(title: str) -> str:
    """The readable form of a title: edition packaging removed, casing kept.

    A work created on the heuristic tier has no authority to name it, so it
    borrows an edition's title — and a book's title has to survive that with
    its capitals intact. ``clean_title`` would render *Red Rising* as
    "red rising" on the cover of its own page.
    """
    if not title:
        return ""
    return re.sub(r"\s+", " ", _strip_edition_noise(title)).strip(" ,:-")


def _strip_volume_marker(title: str) -> str:
    """Drop a trailing volume number, but only when it is clearly a marker.

    A bare trailing integer is stripped only when it is <= 20 *and* at least
    two tokens remain, so ``Red Rising 01`` collapses while ``Fahrenheit 451``,
    ``Catch 22`` and ``Slaughterhouse 5`` do not. An explicit marker word
    (``Vol.``, ``Book``, ``#``) removes that bound — it is unambiguous.
    """
    if _VOLUME_WORD.search(title):
        return _VOLUME_WORD.sub("", title).rstrip(" ,:-")

    match = _VOLUME_MARKER.search(title)
    if match is None:
        return title
    if int(match.group(1)) > _MAX_VOLUME_NUMBER:
        return title
    remainder = title[: match.start()].rstrip(" ,:-")
    if len(remainder.split()) < 2:
        return title
    return remainder


def canonical_key(title: str, author: str | None) -> str:
    """Group key for a work: cleaned title + normalized first author."""
    first_author = (author or "").split(",")[0]
    return f"{clean_title(title)}\x1f{normalize(first_author)}"


def heuristic_external_id(key: str) -> str:
    """Stable synthetic id for a work with no Open Library identity."""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def normalize_isbn(raw: str | None) -> str | None:
    """Return a 13-digit ISBN, upgrading ISBN-10s. None when unusable.

    Open Library returns both forms mixed in one work's ``isbn`` list, so every
    identifier is funnelled through here before comparison.
    """
    if not raw:
        return None
    digits = re.sub(r"[^0-9Xx]", "", raw)
    if len(digits) == 13 and digits.isdigit():
        return digits
    if len(digits) == 10:
        core = "978" + digits[:9]
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
        return core + str((10 - total % 10) % 10)
    return None


def classify_kind(title: str, subtitle: str | None = None) -> str:
    """``"collection"`` for box sets, bundles and omnibuses; else ``"single"``.

    Conservative by design: bare "complete" and bare "collected" are NOT
    matched, so ``The Complete Stories`` and ``Collected Fictions`` stay
    single works. The return value matches ``WorkKind``'s enum values.
    """
    blob = normalize(f"{title or ''} {subtitle or ''}")
    if any(pattern.search(blob) for pattern in _COLLECTION_PATTERNS):
        return "collection"
    return "single"
