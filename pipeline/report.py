"""``report.md`` (spec §7.2): what a reviewer reads before loading a release."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from pipeline.golden import GoldenResult
from pipeline.group.types import PROVENANCE

TOP_WORKS = 5000
MAX_MEMBERS = 40
_LIST_LIMIT = 50


def _table(header: tuple[str, ...], rows) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def _clipped(items: list[str]) -> list[str]:
    extra = len(items) - _LIST_LIMIT
    return items[:_LIST_LIMIT] + ([f"- … and {extra} more"] if extra > 0 else [])


def position_problems(positions: list[float | None]) -> list[str]:
    known = [p for p in positions if p is not None]
    problems = []
    dupes = sorted(p for p, n in Counter(known).items() if n > 1)
    if dupes:
        problems.append("duplicate positions " + ", ".join(f"{p:g}" for p in dupes))
    whole = {int(p) for p in known if p == int(p)}
    if whole:
        gaps = sorted(set(range(min(whole), max(whole) + 1)) - whole)
        if gaps:
            problems.append("gaps at " + ", ".join(str(g) for g in gaps))
    return problems


def _previous_rooms(previous: Path) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """(ol work id -> series key, ol alias -> work id, series key -> slug) from an older release."""
    series = pq.read_table(previous / "series.parquet").to_pylist()
    key_of = {s["id"]: s["key"] for s in series}
    works = pq.read_table(previous / "works.parquet").to_pylist()
    aliases = pq.read_table(previous / "work_aliases.parquet").to_pylist()
    return ({w["ol_work_id"]: key_of[w["series_id"]] for w in works},
            {a["ol_work_id"]: a["work_id"] for a in aliases},
            {s["key"]: s["slug"] for s in series})


def render(con: duckdb.DuckDBPyConnection, version: str, golden: GoldenResult,
           slugs: dict[str, str], previous: Path | None) -> str:
    out = [f"# Catalog release {version}", ""]

    out += ["## Golden set", "",
            f"- membership: {golden.membership_ok}/{golden.total} ({golden.membership_rate:.1%})",
            f"- order: {golden.order_ok}/{golden.total} ({golden.order_rate:.1%})"]
    out += [f"- {f}" for f in golden.failures] + [""]

    counts = [(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in (
        "raw_works", "selected", "works", "editions", "g_works", "g_series", "g_members", "g_aliases")]
    out += ["## Row counts", ""] + _table(("table", "rows"), counts) + [""]
    drops = con.execute("SELECT rule, count(*) FROM select_drops GROUP BY rule ORDER BY rule").fetchall()
    out += ["## Select drops", ""] + _table(("rule", "works"), drops) + [""]

    rungs = con.execute(f"""
        SELECT d.rung FROM g_decisions d JOIN g_works w ON w.ol_id = d.work_ol_id
        ORDER BY w.readinglog_count DESC, w.ol_id LIMIT {TOP_WORKS}""").fetchall()
    tally = Counter("singleton" if r is None else PROVENANCE[r] for (r,) in rungs)
    total = sum(tally.values()) or 1
    out += [f"## Deciding rung ({TOP_WORKS:,} most-read works)", ""]
    out += _table(("rung", "works", "share"), [(k, n, f"{n / total:.1%}") for k, n in sorted(tally.items())]) + [""]

    imprints = con.execute("SELECT key, author_clusters FROM g_imprints ORDER BY key").fetchall()
    out += ["## Imprint rejections", ""] + _table(("series", "author clusters"), imprints) + [""]

    members: dict[str, list[tuple[float | None, str | None]]] = defaultdict(list)
    for key, position, author in con.execute("""
            SELECT m.series_key, m.position, w.primary_author FROM g_members m
            JOIN g_works w ON w.ol_id = m.work_ol_id ORDER BY m.series_key, m.work_ol_id""").fetchall():
        members[key].append((position, author))
    suspicious = []
    for key, rows in sorted(members.items()):
        problems = []
        if len(rows) > MAX_MEMBERS:
            problems.append(f"{len(rows)} members")
        authors = {a for _, a in rows if a}
        if len(authors) > 1:
            problems.append(f"{len(authors)} author clusters")
        problems += position_problems([p for p, _ in rows])
        if problems:
            suspicious.append(f"- `{key}`: " + "; ".join(problems))
    out += ["## Suspicious series", ""] + (_clipped(suspicious) or ["None."]) + [""]

    out += ["## Changes since the previous release", ""]
    if previous is None:
        out += ["First release.", ""]
        return "\n".join(out)
    old_rooms, old_aliases, old_slugs = _previous_rooms(previous)
    rooms = dict(con.execute("SELECT ol_id, room FROM g_works").fetchall())
    aliases = dict(con.execute("SELECT ol_id, work_ol_id FROM g_aliases").fetchall())
    moved = [f"- {ol}: `{old}` → `{rooms[ol]}`" for ol, old in sorted(old_rooms.items())
             if ol in rooms and rooms[ol] != old]
    merged = [f"- {ol} → {aliases[ol]}" for ol in sorted(aliases) if ol not in old_aliases]
    gone = [f"- {ol}" for ol in sorted(old_rooms) if ol not in rooms and ol not in aliases]
    reslugged = [f"- `{k}`: {s} → {slugs[k]}" for k, s in sorted(old_slugs.items()) if k in slugs and slugs[k] != s]
    out += [f"Compared with `{previous.name}`.", ""]
    for title, items in (("Changed series", moved), ("Newly merged", merged),
                         ("Disappeared", gone), ("Slug changes", reslugged)):
        out += [f"### {title} ({len(items)})", ""] + (_clipped(items) or ["None."]) + [""]
    return "\n".join(out)
