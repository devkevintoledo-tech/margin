"""The series decision ladder's evidence (spec §5.3, rungs 1-4).

Each function turns one kind of evidence into candidates. Choosing between
them — and the guards — live in ``guards.py`` and ``decide.py``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable, Mapping, Sequence

from pipeline._backend import choose_container, parse_tags, series_key, tag_name
from pipeline.group.types import Candidate, GWork, WdMembership, WdSeries
from pipeline.parse.series_strings import SeriesRef, parse_series_string, parse_title_series

_ORDINAL = re.compile(r"^\d{1,4}(?:\.\d+)?$")


def parse_ordinal(raw: str | None) -> float | None:
    """Wikidata P1545 as a number; "1a" or "I" is no position at all."""
    text = (raw or "").strip()
    return float(text) if _ORDINAL.match(text) else None


def ol_key(name: str) -> str | None:
    key = series_key(name)
    return f"ol:{key}" if key else None


def wd_label(wd_series: Mapping[str, WdSeries], qid: str) -> str:
    series = wd_series.get(qid)
    if series is None:
        return qid
    return series.label or (min(series.aliases) if series.aliases else qid)


def rung1(work: GWork, by_item: Mapping[str, Sequence[WdMembership]],
          wd_series: Mapping[str, WdSeries]) -> list[Candidate]:
    found: dict[str, Candidate] = {}
    for item in sorted(work.wd_items):
        for m in by_item.get(item, ()):
            key = f"wd:{m.series}"
            position = parse_ordinal(m.ordinal)
            prior = found.get(key)
            if prior is None or (prior.position is None and position is not None):
                found[key] = Candidate(key, wd_label(wd_series, m.series), position, 1)
    return [found[k] for k in sorted(found)]


def count_tags(works: Iterable[GWork]) -> Counter[str]:
    """How many catalog works carry each series tag — counted over the whole catalog."""
    counts: Counter[str] = Counter()
    for work in works:
        tags = parse_tags(work.subjects)
        counts.update(set(tags.series))
    return counts


def rung2(work: GWork, tag_counts: Mapping[str, int]) -> Candidate | None:
    tag = choose_container(parse_tags(work.subjects), tag_counts)
    if tag is None:
        return None
    name = tag_name(tag)
    key = ol_key(name)
    return Candidate(key, name, None, 2) if key else None


def _vote(refs_per_voter: Iterable[Iterable[SeriesRef]], rung: int) -> Candidate | None:
    """Majority vote: one vote per voter per series, positions voted within the winner."""
    votes: Counter[str] = Counter()
    names: dict[str, Counter[str]] = defaultdict(Counter)
    positions: dict[str, Counter[float]] = defaultdict(Counter)
    for refs in refs_per_voter:
        seen: set[str] = set()
        for ref in refs:
            key = ol_key(ref.name)
            if key is None or key in seen:
                continue
            seen.add(key)
            votes[key] += 1
            names[key][ref.name] += 1
            if ref.position is not None:
                positions[key][ref.position] += 1
    if not votes:
        return None
    key = min(votes, key=lambda k: (-votes[k], k))
    name = min(names[key], key=lambda n: (-names[key][n], n))
    pos_votes = positions[key]
    position = min(pos_votes, key=lambda p: (-pos_votes[p], p)) if pos_votes else None
    return Candidate(key, name, position, rung)


def rung3(work: GWork) -> Candidate | None:
    return _vote(
        ([r for r in (parse_series_string(raw) for raw in edition) if r] for edition in work.edition_series),
        rung=3,
    )


def rung4(work: GWork) -> Candidate | None:
    return _vote(([r] if (r := parse_title_series(t)) else [] for t in work.titles), rung=4)


def candidates(work: GWork, by_item: Mapping[str, Sequence[WdMembership]],
               wd_series: Mapping[str, WdSeries], tag_counts: Mapping[str, int]) -> list[Candidate]:
    found = rung1(work, by_item, wd_series)
    found += [c for c in (rung2(work, tag_counts), rung3(work), rung4(work)) if c is not None]
    return found
