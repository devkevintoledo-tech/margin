"""Series detection rules: pure string work over Open Library subject tags.

Open Library already carries the hierarchy a series page needs, in rows we
store: ``franchise:Red Rising`` spans the whole saga, ``series:Red Rising
Trilogy`` a run inside it. No I/O here — the same shape and the same reason as
``work_identity.py``: these rules decide which room a conversation lives in, so
they are tested as a table.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping, NamedTuple, Sequence

# Subjects are stored one per line. They used to be space-joined, which erased
# the boundary between "franchise:Red Rising" and the next subject.
SUBJECT_SEPARATOR = "\n"

_PREFIXES = ("franchise", "series")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


class SeriesTags(NamedTuple):
    franchises: tuple[str, ...]
    series: tuple[str, ...]


def join_subjects(subjects: Sequence[str]) -> str | None:
    return SUBJECT_SEPARATOR.join(subjects) or None


def _clean_name(raw: str) -> str:
    return _SPACE.sub(" ", raw.replace("_", " ")).strip()


def parse_tags(subjects: str | None) -> SeriesTags:
    """Pull franchise and series tags out of a stored subject blob.

    A tag name never contains ':'. A line that does is a legacy space-joined
    blob holding several tags, and guessing where one ends would put books in
    the wrong room — so it is ignored and the work stays a singleton until the
    backfill re-fetches its subjects.
    """
    found: dict[str, list[str]] = {p: [] for p in _PREFIXES}
    for line in (subjects or "").split(SUBJECT_SEPARATOR):
        prefix, sep, rest = line.strip().partition(":")
        prefix = prefix.lower()
        if not sep or prefix not in found or ":" in rest:
            continue
        name = _clean_name(rest)
        tag = f"{prefix}:{name}"
        if name and tag not in found[prefix]:
            found[prefix].append(tag)
    return SeriesTags(tuple(found["franchise"]), tuple(found["series"]))


def choose_container(tags: SeriesTags, counts: Mapping[str, int]) -> str | None:
    """The tag whose series becomes the work's room.

    A franchise is the whole saga, so it wins outright. Otherwise the series
    tag shared by the most works in the catalog wins — the broadest grouping is
    the one-room goal — with the name as a deterministic tiebreak.
    """
    if tags.franchises:
        return min(tags.franchises)
    if tags.series:
        return min(tags.series, key=lambda t: (-counts.get(t, 0), t))
    return None


def tag_name(tag: str) -> str:
    return tag.partition(":")[2]


def series_key(name: str) -> str:
    return _SPACE.sub(" ", _NON_WORD.sub(" ", name.lower())).strip()


def tag_external_id(tag: str) -> str:
    """Identity of a tag series: casing and punctuation variants are one series."""
    prefix, _, name = tag.partition(":")
    return f"{prefix}:{series_key(name)}"


def slugify(name: str, max_length: int = 80) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower().replace("'", "")).strip("-")
    if len(cleaned) > max_length:
        window = cleaned[:max_length]
        if cleaned[max_length] != "-" and "-" in window:
            window = window[: window.rindex("-")]
        cleaned = window.strip("-")
    return cleaned or "series"
