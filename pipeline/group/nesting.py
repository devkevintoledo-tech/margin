"""Series nesting and rooms (spec §5.3, "Nesting").

A work's room is the top of its membership's parent chain, but a parent only
becomes a room when it has at least two direct works or two child series — a
sprawling "universe" item cannot swallow unrelated books.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping


def rooms(memberships: Mapping[str, Iterable[str]],
          parents: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str | None]]:
    """Return ``(room of each work, parent of each output series)``.

    ``memberships`` maps a work to its series keys; works with none are left
    out (they become singletons). ``parents`` maps a series key to its
    parent's key. The second result holds every series the release needs —
    members' series plus the chain above them up to each room.
    """
    member_keys = {w: set(keys) for w, keys in memberships.items() if keys}
    direct: Counter[str] = Counter(k for keys in member_keys.values() for k in keys)

    relevant = set(direct)
    frontier = list(relevant)
    while frontier:
        parent = parents.get(frontier.pop())
        if parent and parent not in relevant:
            relevant.add(parent)
            frontier.append(parent)
    children: dict[str, set[str]] = defaultdict(set)
    for key in relevant:
        if parents.get(key):
            children[parents[key]].add(key)

    def qualifies(key: str) -> bool:
        return direct[key] >= 2 or len(children[key]) >= 2

    def chain(key: str) -> list[str]:
        path = [key]
        while (parent := parents.get(path[-1])) and parent not in path and qualifies(parent):
            path.append(parent)
        return path

    chains = {k: chain(k) for k in direct}
    tops = {w: sorted({chains[k][-1] for k in keys}) for w, keys in member_keys.items()}
    size = Counter(t for ts in tops.values() for t in ts)
    room = {w: min(ts, key=lambda t: (-size[t], t)) for w, ts in tops.items()}

    output = {k for path in chains.values() for k in path}
    parent_of = {k: (parents[k] if parents.get(k) in output else None) for k in sorted(output)}
    return room, parent_of
