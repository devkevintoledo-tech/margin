"""The golden set (spec §7.1): widely read series with known members and order.

``publish`` refuses to write a release unless at least 95% of golden series
have exactly the expected membership and 95% exactly the expected order.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

import yaml

THRESHOLD = 0.95


class GoldenGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoldenSeries:
    name: str
    members: tuple[str, ...]  # OL work ids, in reading order


@dataclass(frozen=True)
class MemberRow:
    work: str
    position: float | None
    first_publish_year: int | None
    title: str


@dataclass
class GoldenResult:
    total: int = 0
    membership_ok: int = 0
    order_ok: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def membership_rate(self) -> float:
        return self.membership_ok / self.total if self.total else 0.0

    @property
    def order_rate(self) -> float:
        return self.order_ok / self.total if self.total else 0.0


def load_golden(path: Path) -> list[GoldenSeries]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return [GoldenSeries(e["name"], tuple(e["members"])) for e in entries or []]


def reading_order(rows: Sequence[MemberRow]) -> list[str]:
    """The series page's order: position, then first publication, then title."""
    return [r.work for r in sorted(rows, key=lambda r: (
        r.position is None, r.position or 0.0,
        r.first_publish_year is None, r.first_publish_year or 0, r.title, r.work))]


def evaluate(golden: Sequence[GoldenSeries], members: Mapping[str, Sequence[MemberRow]],
             resolve: Callable[[str], str] = lambda w: w) -> GoldenResult:
    """Compare each golden series with the release series most of its works landed in."""
    series_of: dict[str, set[str]] = defaultdict(set)
    for key, rows in members.items():
        for row in rows:
            series_of[row.work].add(key)
    result = GoldenResult(total=len(golden))
    for g in golden:
        expected = [resolve(w) for w in g.members]
        votes = Counter(k for w in expected for k in series_of[w])
        if not votes:
            result.failures.append(f"{g.name}: none of its works is in any series")
            continue
        key = min(votes, key=lambda k: (-votes[k], k))
        actual = reading_order(members[key])
        if set(actual) == set(expected):
            result.membership_ok += 1
        else:
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            result.failures.append(f"{g.name} ({key}): missing {missing}, unexpected {extra}")
        if actual == expected:
            result.order_ok += 1
        elif set(actual) == set(expected):
            result.failures.append(f"{g.name} ({key}): order {actual}, expected {expected}")
    return result


def gate(result: GoldenResult, threshold: float = THRESHOLD) -> None:
    if result.total == 0:
        raise GoldenGateError("the golden set is empty; see pipeline/golden/README.md")
    if result.membership_rate < threshold or result.order_rate < threshold:
        detail = "\n  ".join(result.failures)
        raise GoldenGateError(
            f"golden set: membership {result.membership_rate:.1%}, order {result.order_rate:.1%} "
            f"(need {threshold:.0%})\n  {detail}")


def draft_from_wikidata(con, qid: str) -> str:
    """A golden entry drafted from Wikidata's own ordinals, for a human to verify.

    Drafted from the fetched Wikidata rows, never from the pipeline's grouping
    output: a golden set built from the output would only test itself.
    """
    from pipeline.group.ladder import parse_ordinal
    from pipeline.sources.load_raw import resolver

    resolve = resolver(dict(con.execute("SELECT from_ol, to_ol FROM raw_work_redirects").fetchall()))
    owner = dict(con.execute("SELECT ol_id, work_ol_id FROM raw_editions").fetchall())
    titles = dict(con.execute("SELECT ol_id, title FROM works").fetchall())
    label = con.execute("SELECT label FROM wd_series WHERE qid = ?", [qid]).fetchone()
    found: dict[str, float | None] = {}
    for ol_id, ordinal in con.execute("SELECT ol_id, ordinal FROM wd_memberships WHERE series = ?", [qid]).fetchall():
        work = resolve(ol_id) if ol_id.endswith("W") else owner.get(ol_id)
        if work:
            position = parse_ordinal(ordinal)
            found[work] = position if found.get(work) is None else found[work]
    ordered = sorted(found, key=lambda w: (found[w] is None, found[w] or 0.0, w))
    lines = [f"- name: {(label[0] if label else qid)!r}", f"  # drafted from wd:{qid}; verify against the author's or publisher's list",
             "  verified_by: ''", "  members:"]
    lines += [f"    - {w}  # {found[w] if found[w] is not None else '?'}: {titles.get(w, 'NOT IN CATALOG')}" for w in ordered]
    return "\n".join(lines) + "\n"
