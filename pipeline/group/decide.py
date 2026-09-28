"""Membership decisions: the ladder, its guards, one result (spec §5.3)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from pipeline._backend import series_key
from pipeline.group.guards import drop_adaptations, fold_map, imprint_rejections
from pipeline.group.ladder import candidates, count_tags, wd_label
from pipeline.group.types import Candidate, GWork, Membership, WdMembership, WdSeries


@dataclass
class Decision:
    memberships: dict[str, dict[str, Membership]]  # work -> series key -> membership
    names: dict[str, str]  # series key -> display name
    rejected: dict[str, int]  # imprint key -> author clusters
    decided_by: dict[str, int | None]  # work -> winning rung (None = singleton)
    known_series: set[str] = field(default_factory=set)  # every key the build has evidence for
    folded: dict[str, str] = field(default_factory=dict)  # series key -> the key it folded into


def _names(cands: Mapping[str, Sequence[Candidate]], wd_series: Mapping[str, WdSeries]) -> dict[str, str]:
    raw: dict[str, Counter[str]] = defaultdict(Counter)
    for cs in cands.values():
        for c in cs:
            if c.rung > 1:
                raw[c.key][c.name] += 1
    names = {k: min(v, key=lambda n: (-v[n], n)) for k, v in raw.items()}
    names.update({f"wd:{qid}": wd_label(wd_series, qid) for qid in wd_series})
    return names


def decide(works: Sequence[GWork], wd_memberships: Iterable[WdMembership],
           wd_series: Mapping[str, WdSeries], blocklist: Iterable[str] = (),
           rejects: Iterable[str] = ()) -> Decision:
    """``blocklist`` holds imprint names; ``rejects`` holds series keys from overrides."""
    by_item: dict[str, list[WdMembership]] = defaultdict(list)
    for m in wd_memberships:
        by_item[m.item].append(m)
    tag_counts = count_tags(works)
    cands = {w.ol_id: candidates(w, by_item, wd_series, tag_counts) for w in works}
    primary = {w.ol_id: w.primary_author for w in works}

    blocked = {f"ol:{series_key(n)}" for n in blocklist} | set(rejects)
    rejected = imprint_rejections(cands, primary, blocked)
    fold = fold_map(cands, wd_series, rejected)

    memberships: dict[str, dict[str, Membership]] = {}
    for work in works:
        mapped = sorted(
            (Candidate(fold.get(c.key, c.key), c.name,
                       None if work.kind == "collection" else c.position, c.rung)
             for c in cands[work.ol_id] if c.key not in rejected),
            key=lambda c: c.rung,
        )
        top = [c for c in mapped if c.rung == 1] or mapped[:1]
        chosen: dict[str, Membership] = {}
        for c in top:
            if c.key in chosen:
                continue
            position = next((o.position for o in mapped if o.key == c.key and o.position is not None), None)
            chosen[c.key] = Membership(c.key, position, c.rung)
        memberships[work.ol_id] = chosen

    drop_adaptations(memberships, primary)

    # A title pattern alone, seen on one book, is too weak to stand up a series.
    holders: dict[str, list[Membership]] = defaultdict(list)
    for ms in memberships.values():
        for m in ms.values():
            holders[m.key].append(m)
    lonely = {k for k, ms in holders.items() if len(ms) == 1 and ms[0].rung == 4}
    for ms in memberships.values():
        for key in lonely & ms.keys():
            del ms[key]

    decided_by = {w: (min(m.rung for m in ms.values()) if ms else None) for w, ms in memberships.items()}
    known = {c.key for cs in cands.values() for c in cs} | set(fold.values()) | {f"wd:{q}" for q in wd_series}
    return Decision(memberships, _names(cands, wd_series), rejected, decided_by, known, dict(fold))
