"""Guards on the ladder (spec §5.3): imprints, folding, adaptations."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping, Sequence

from pipeline._backend import series_key
from pipeline.group.types import Candidate, Membership, WdSeries

# A rung 2-4 series spanning more author clusters than this is a publisher
# imprint (Penguin Classics, "A Del Rey book"), not a series.
MAX_AUTHOR_CLUSTERS = 3


def imprint_rejections(cands: Mapping[str, Sequence[Candidate]],
                       primary: Mapping[str, str | None],
                       blocked: Iterable[str] = ()) -> dict[str, int]:
    """``{series key: author clusters}`` for every rejected rung 2-4 series."""
    clusters: dict[str, set[str]] = defaultdict(set)
    for work, cs in cands.items():
        author = primary.get(work)
        for c in cs:
            if c.rung > 1 and author is not None:
                clusters[c.key].add(author)
    rejected = {k: len(v) for k, v in clusters.items() if len(v) > MAX_AUTHOR_CLUSTERS}
    for key in blocked:
        if key in clusters:
            rejected.setdefault(key, len(clusters[key]))
    return rejected


def _follow(mapping: Mapping[str, str], key: str) -> str:
    seen = {key}
    while key in mapping and mapping[key] not in seen:
        key = mapping[key]
        seen.add(key)
    return key


def fold_map(cands: Mapping[str, Sequence[Candidate]], wd_series: Mapping[str, WdSeries],
             rejected: Iterable[str] = ()) -> dict[str, str]:
    """Where each rung 2-4 series folds, as ``{ol key: surviving key}``.

    Folds into a Wikidata series whose label or alias has the same
    ``series_key``; otherwise into whichever stronger series (Wikidata, or an
    OL series from a higher rung) at least half of its works already carry.
    The second rule is what joins "Red Rising Saga ; 5" on an edition to the
    ``franchise:Red Rising`` tag its siblings carry.
    """
    rejected = set(rejected)
    wd_by_name: dict[str, set[str]] = defaultdict(set)
    for qid, s in wd_series.items():
        for name in (s.label, *s.aliases):
            if name:
                wd_by_name[series_key(name)].add(f"wd:{qid}")
    rung1_members = Counter(c.key for cs in cands.values() for c in cs if c.rung == 1)
    ol_keys = sorted({c.key for cs in cands.values() for c in cs if c.rung > 1} - rejected)

    mapping: dict[str, str] = {}
    for key in ol_keys:
        targets = wd_by_name.get(key[len("ol:"):])
        if targets:
            mapping[key] = min(targets, key=lambda t: (-rung1_members[t], t))

    carriers: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for work, cs in cands.items():
        for c in cs:
            if c.rung > 1 and c.key in ol_keys:
                carriers[c.key].append((work, c.rung))
    for key in ol_keys:
        if key in mapping:
            continue
        votes: Counter[str] = Counter()
        for work, rung in carriers[key]:
            stronger = {mapping.get(c.key, c.key) for c in cands[work]
                        if c.rung < rung and c.key not in rejected} - {key}
            votes.update(stronger)
        if votes:
            target, n = min(votes.items(), key=lambda kv: (-kv[1], kv[0]))
            if 2 * n >= len(carriers[key]):
                mapping[key] = target
    return {k: _follow(mapping, k) for k in mapping}


def drop_adaptations(memberships: dict[str, dict[str, Membership]],
                     primary: Mapping[str, str | None]) -> None:
    """Remove rung 2-4 members not by the series' dominant author cluster.

    Graphic-novel adaptations, companions and game books by other authors
    stay out. Wikidata (rung 1) is trusted over this rule.
    """
    holders: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for work, ms in memberships.items():
        for key, m in ms.items():
            holders[key].append((work, m.rung))
    for key, members in holders.items():
        authors = Counter(primary[w] for w, _ in members if primary.get(w) is not None)
        if not authors:
            continue
        dominant = min(authors, key=lambda a: (-authors[a], a))
        for work, rung in members:
            if rung != 1 and primary.get(work) != dominant:
                del memberships[work][key]
