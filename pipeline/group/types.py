"""Plain value types the grouping rules pass between each other."""

from __future__ import annotations

from dataclasses import dataclass

# Ladder rungs (spec §5.3). 0 marks a membership set by an override.
OVERRIDE_RUNG = 0
PROVENANCE = {0: "override", 1: "wikidata", 2: "ol_tag", 3: "ol_edition_series", 4: "title_pattern"}
CONFIDENCE = {0: "high", 1: "high", 2: "medium", 3: "medium", 4: "low"}


@dataclass(frozen=True)
class GWork:
    """A work as the ladder sees it."""

    ol_id: str
    titles: tuple[str, ...]  # the work's raw title first, then its English editions' raw titles
    primary_author: str | None  # author cluster id
    kind: str  # "single" | "collection"
    subjects: str | None  # one subject per line
    edition_series: tuple[tuple[str, ...], ...]  # each English edition's raw `series` strings
    wd_items: frozenset[str]  # Wikidata items linked by P648 to the work or one of its editions
    first_publish_year: int | None = None


@dataclass(frozen=True)
class WdMembership:
    item: str  # Q-id of the book
    series: str  # Q-id of the series
    ordinal: str | None  # raw P1545 value


@dataclass(frozen=True)
class WdSeries:
    qid: str
    label: str | None
    aliases: tuple[str, ...] = ()
    parents: tuple[str, ...] = ()  # Q-ids via P179 or P361


@dataclass(frozen=True)
class Candidate:
    """One rung's claim that a work belongs to a series."""

    key: str  # "wd:Q45875" or "ol:<series_key>"
    name: str
    position: float | None
    rung: int


@dataclass(frozen=True)
class Membership:
    key: str
    position: float | None
    rung: int
