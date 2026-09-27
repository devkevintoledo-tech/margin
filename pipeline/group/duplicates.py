"""Duplicate works (spec §5.2): two OL records of one book.

Same primary-author cluster and same cleaned title merge, unless the
evidence says they are different books: each linked to a different Wikidata
item, or editions that share no title at all (Open Library titles three
different Brian Herbert books plain "Dune"; their editions say *House
Atreides*, *House Harkonnen*, *House Corrino*).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from pipeline._backend import clean_title

_OL_NUMBER = re.compile(r"\d+")


@dataclass(frozen=True)
class DupWork:
    ol_id: str
    primary_author: str | None
    title_key: str  # clean_title of the work title
    kind: str
    wd_items: frozenset[str]
    edition_titles: frozenset[str]  # edition_title_key of each English edition
    popularity: int  # readinglog_count + edition_count


def edition_title_key(title: str | None, subtitle: str | None) -> str:
    """An edition's title for the duplicate guard, subtitle included.

    Open Library titles every edition of Brian Herbert's *House* books plain
    "Dune"; only the subtitle ("House Atreides") tells them apart, so a key
    without it would call three books one.
    """
    return clean_title(" ".join(t for t in (title, subtitle) if t))


def _ol_number(ol_id: str) -> int:
    match = _OL_NUMBER.search(ol_id)
    return int(match.group()) if match else 0


def _rank(work: DupWork) -> tuple[int, int, int]:
    """Survivor order: Wikidata-linked, then more popular, then lower OL id."""
    return (0 if work.wd_items else 1, -work.popularity, _ol_number(work.ol_id))


def _compatible(a: DupWork, b: DupWork) -> bool:
    if a.wd_items and b.wd_items and a.wd_items.isdisjoint(b.wd_items):
        return False
    if a.edition_titles and b.edition_titles and a.edition_titles.isdisjoint(b.edition_titles):
        return False
    return True


def find_duplicates(works: Sequence[DupWork]) -> dict[str, str]:
    """``{loser_ol_id: survivor_ol_id}``. Collections never merge."""
    groups: dict[tuple[str, str], list[DupWork]] = defaultdict(list)
    for work in works:
        if work.primary_author is None or work.kind == "collection" or not work.title_key:
            continue
        groups[(work.primary_author, work.title_key)].append(work)

    losers: dict[str, str] = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        clusters: list[list[DupWork]] = []
        for work in sorted(group, key=_rank):
            home = next((c for c in clusters if all(_compatible(work, m) for m in c)), None)
            if home is None:
                clusters.append([work])
            else:
                home.append(work)
        for survivor, *rest in clusters:
            for loser in rest:
                losers[loser.ol_id] = survivor.ol_id
    return losers
