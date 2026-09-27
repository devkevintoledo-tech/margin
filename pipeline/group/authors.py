"""Author clusters (spec §5.1): 刘慈欣 = Cixin Liu = Liu Cixin.

Every later author comparison is between clusters, never strings. A cluster's
id is its smallest OL author id, so it is stable across runs.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from pipeline._backend import normalize

# A name carried by more records than this is a common name ("John Smith"),
# not one person catalogued several times, and never unions anyone.
MAX_NAME_SHARERS = 3
_NON_LATIN = re.compile(r"[^\x00-ɏ]")


@dataclass(frozen=True)
class AuthorRec:
    ol_id: str
    name: str
    alternate_names: tuple[str, ...] = ()
    wikidata: str | None = None  # from the OL record's remote_ids


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # The smaller id is the root, which makes it the cluster id.
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def _distinctive(name: str) -> bool:
    """Two or more words, or a non-Latin name: specific enough to match on."""
    return len(name.split()) >= 2 or (len(name) >= 2 and bool(_NON_LATIN.search(name)))


def cluster_authors(
    authors: Iterable[AuthorRec],
    wd_author_ids: Iterable[tuple[str, str]] = (),
    wd_names: Iterable[tuple[str, str]] = (),
) -> dict[str, str]:
    """Map every OL author id to its cluster id.

    ``wd_author_ids`` is ``(qid, ol_author_id)`` from Wikidata P648;
    ``wd_names`` is ``(qid, name)`` — labels and aliases of those items.
    """
    records = {a.ol_id: a for a in authors}
    uf = _UnionFind(records)

    # 1. One Wikidata item, many OL records: the strongest evidence there is.
    by_qid: dict[str, set[str]] = defaultdict(set)
    for a in records.values():
        if a.wikidata:
            by_qid[a.wikidata].add(a.ol_id)
    for qid, ol_id in wd_author_ids:
        if ol_id in records:
            by_qid[qid].add(ol_id)
    for members in by_qid.values():
        first, *rest = sorted(members)
        for other in rest:
            uf.union(first, other)

    # 2. Shared distinctive names, from OL alternate_names and Wikidata aliases.
    qids_of: dict[str, set[str]] = defaultdict(set)
    for qid, members in by_qid.items():
        for ol_id in members:
            qids_of[ol_id].add(qid)
    wd_name_map: dict[str, set[str]] = defaultdict(set)
    for qid, name in wd_names:
        wd_name_map[qid].add(name)

    carriers: dict[str, set[str]] = defaultdict(set)
    for a in records.values():
        names = {a.name, *a.alternate_names}
        for qid in qids_of[a.ol_id]:
            names |= wd_name_map[qid]
        for name in names:
            key = normalize(name)
            if key and _distinctive(key):
                carriers[key].add(a.ol_id)
    for members in carriers.values():
        if 2 <= len(members) <= MAX_NAME_SHARERS:
            first, *rest = sorted(members)
            for other in rest:
                uf.union(first, other)

    return {ol_id: uf.find(ol_id) for ol_id in records}
