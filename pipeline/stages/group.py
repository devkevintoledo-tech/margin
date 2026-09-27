"""group (spec §5): author clusters, duplicates, the ladder, overrides, rooms."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Mapping, Sequence

import pyarrow as pa
import yaml

from pipeline._backend import clean_title
from pipeline.config import BuildContext
from pipeline.db import swap_in, write_table
from pipeline.group.authors import AuthorRec, cluster_authors
from pipeline.group.decide import decide
from pipeline.group.duplicates import DupWork, edition_title_key, find_duplicates
from pipeline.group.nesting import rooms
from pipeline.group.types import CONFIDENCE, PROVENANCE, GWork, WdMembership, WdSeries
from pipeline.overrides import apply_identity, apply_series, load_overrides, series_rejects
from pipeline.sources.load_raw import resolver
from pipeline.stages.extract import EDITIONS_SCHEMA, WORKS_SCHEMA

_OL_NUMBER = re.compile(r"\d+")
_SUMMED = ("ratings_count", "readinglog_count", "edition_count")
G_WORKS_SCHEMA = WORKS_SCHEMA.append(pa.field("primary_author", pa.string())).append(
    pa.field("room", pa.string())).append(pa.field("representative_edition", pa.string()))


def _number(ol_id: str) -> int:
    match = _OL_NUMBER.search(ol_id)
    return int(match.group()) if match else 0


def representative(editions: Sequence[Mapping], work_cover: int | None) -> str | None:
    """The edition that speaks for the work: its curated cover, then any cover, ISBN, pages."""
    if not editions:
        return None
    return min(editions, key=lambda e: (
        e["cover_id"] is None or e["cover_id"] != work_cover, e["cover_id"] is None,
        e["isbn_13"] is None, e["page_count"] is None, _number(e["ol_id"])))["ol_id"]


def _table(con, sql: str) -> list[dict]:
    cursor = con.execute(sql)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def run(ctx: BuildContext) -> None:
    con = ctx.con
    overrides = load_overrides(ctx.overrides_dir)
    blocklist = yaml.safe_load((ctx.rules_dir / "imprints.yaml").read_text(encoding="utf-8")) or []

    works = {w["ol_id"]: w for w in _table(con, "SELECT * FROM works ORDER BY ol_id")}
    editions = _table(con, "SELECT * FROM editions ORDER BY ol_id")
    clusters = cluster_authors(
        [AuthorRec(a["ol_id"], a["name"], tuple(a["alternate_names"]), a["wikidata"])
         for a in _table(con, "SELECT * FROM authors ORDER BY ol_id")],
        con.execute("SELECT qid, ol_author_id FROM wd_author_ids").fetchall(),
        con.execute("SELECT qid, name FROM wd_author_names").fetchall(),
    )

    resolve_work = resolver(dict(con.execute("SELECT from_ol, to_ol FROM raw_work_redirects").fetchall()))
    edition_owner = dict(con.execute("SELECT ol_id, work_ol_id FROM raw_editions").fetchall())
    memberships: list[WdMembership] = []
    wd_items: dict[str, set[str]] = defaultdict(set)
    wd_by_edition: dict[str, set[str]] = defaultdict(set)
    for item, series, ordinal, ol_id in con.execute("SELECT item, series, ordinal, ol_id FROM wd_memberships").fetchall():
        memberships.append(WdMembership(item, series, ordinal))
        if ol_id.endswith("M"):
            wd_by_edition[ol_id].add(item)
        work = resolve_work(ol_id) if ol_id.endswith("W") else edition_owner.get(ol_id)
        if work:
            wd_items[work].add(item)
    wd_series = {r["qid"]: WdSeries(r["qid"], r["label"], tuple(r["aliases"]), tuple(r["parents"]))
                 for r in _table(con, "SELECT * FROM wd_series")}

    def primary(work: Mapping) -> str | None:
        return clusters.get(work["author_ids"][0]) if work["author_ids"] else None

    by_work: dict[str, list[dict]] = defaultdict(list)
    for e in editions:
        by_work[e["work_ol_id"]].append(e)

    # 5.2 — duplicates, then identity overrides.
    dups = find_duplicates([
        DupWork(ol, primary(w), clean_title(w["title"]), w["kind"], frozenset(wd_items[ol]),
                frozenset(edition_title_key(e["title"], e["subtitle"]) for e in by_work[ol]), w["readinglog_count"] + w["edition_count"])
        for ol, w in works.items()
    ])
    plan = apply_identity(overrides, set(works), {e["ol_id"]: e["work_ol_id"] for e in editions}, dups)
    final: dict[str, dict] = {ol: dict(w) for ol, w in works.items() if ol not in plan.aliases}
    for loser, survivor in sorted(plan.aliases.items()):
        for field in _SUMMED:
            final[survivor][field] += works[loser][field]
        wd_items[survivor] |= wd_items[loser]
    for split in plan.splits:
        first = next(e for e in editions if e["ol_id"] == min(split.editions))
        source = final[plan.aliases.get(split.work, split.work)]
        final[split.new_work] = {**source, "ol_id": split.new_work, "raw_title": first["title"],
                                 "title": first["title"], "subtitle": first["subtitle"], "subjects": None,
                                 "cover_id": first["cover_id"], "ratings_count": 0, "readinglog_count": 0,
                                 "edition_count": len(split.editions)}
        wd_items[split.new_work] = set().union(*(wd_by_edition[e] for e in split.editions))
    for e in editions:
        e["work_ol_id"] = plan.edition_work[e["ol_id"]]
    by_work = defaultdict(list)
    for e in editions:
        by_work[e["work_ol_id"]].append(e)

    # 5.3 — the ladder, its guards, series overrides, rooms.
    gworks = [
        GWork(ol, (w["raw_title"], *(e["title"] for e in by_work[ol])), primary(w), w["kind"], w["subjects"],
              tuple(tuple(e["series"]) for e in by_work[ol]), frozenset(wd_items[ol]), w["first_publish_year"])
        for ol, w in sorted(final.items())
    ]
    decision = decide(gworks, memberships, wd_series, blocklist, series_rejects(overrides))
    apply_series(overrides, decision, set(final), resolve=lambda ol: plan.aliases.get(ol, ol))
    parents = {f"wd:{q}": f"wd:{min(s.parents)}" for q, s in wd_series.items() if s.parents}
    room, parent_of = rooms({w: ms.keys() for w, ms in decision.memberships.items()}, parents)

    series_rows, member_rows = [], []
    rungs: dict[str, list[int]] = defaultdict(list)
    for work, ms in sorted(decision.memberships.items()):
        for key, m in sorted(ms.items()):
            rungs[key].append(m.rung)
            member_rows.append({"series_key": key, "work_ol_id": work, "position": m.position,
                                "provenance": PROVENANCE[m.rung], "confidence": CONFIDENCE[m.rung]})
    for key, parent in sorted(parent_of.items()):
        if key.startswith("wd:"):
            source, provenance = "wikidata", "wikidata"
        else:
            real = [r for r in rungs[key] if r > 0]
            source, provenance = "openlibrary", PROVENANCE[min(real)] if real else "override"
        series_rows.append({"key": key, "name": decision.names.get(key, key), "source": source,
                            "provenance": provenance, "kind": "series", "parent_key": parent})
    for ol, w in sorted(final.items()):
        if ol not in room:
            room[ol] = f"single:{ol}"
            series_rows.append({"key": room[ol], "name": w["title"], "source": "heuristic",
                                "provenance": "single", "kind": "singleton", "parent_key": None})

    redirect_aliases = con.execute("SELECT from_ol, to_ol FROM raw_work_aliases").fetchall()
    aliases = dict(plan.aliases)
    for old, target in redirect_aliases:
        survivor = plan.aliases.get(target, target)
        if survivor in final and old not in final:
            aliases[old] = survivor

    g_works = [{**w, "primary_author": primary(w), "room": room[ol],
                "representative_edition": representative(by_work[ol], w["cover_id"])}
               for ol, w in sorted(final.items())]
    write_table(con, "g_works", pa.Table.from_pylist(g_works, schema=G_WORKS_SCHEMA))
    write_table(con, "g_editions", pa.Table.from_pylist(editions, schema=EDITIONS_SCHEMA))
    write_table(con, "g_series", pa.Table.from_pylist(series_rows, schema=pa.schema([
        ("key", pa.string()), ("name", pa.string()), ("source", pa.string()), ("provenance", pa.string()),
        ("kind", pa.string()), ("parent_key", pa.string())])))
    write_table(con, "g_members", pa.Table.from_pylist(member_rows, schema=pa.schema([
        ("series_key", pa.string()), ("work_ol_id", pa.string()), ("position", pa.float64()),
        ("provenance", pa.string()), ("confidence", pa.string())])))
    write_table(con, "g_aliases", pa.table({"ol_id": pa.array(sorted(aliases), pa.string()),
                                            "work_ol_id": pa.array([aliases[k] for k in sorted(aliases)], pa.string())}))
    write_table(con, "g_decisions", pa.table({
        "work_ol_id": pa.array(sorted(decision.decided_by), pa.string()),
        "rung": pa.array([decision.decided_by[k] for k in sorted(decision.decided_by)], pa.int8())}))
    write_table(con, "g_imprints", pa.table({
        "key": pa.array(sorted(decision.rejected), pa.string()),
        "author_clusters": pa.array([decision.rejected[k] for k in sorted(decision.rejected)], pa.int32())}))
    write_table(con, "g_author_clusters", pa.table({
        "ol_author_id": pa.array(sorted(clusters), pa.string()),
        "cluster_id": pa.array([clusters[k] for k in sorted(clusters)], pa.string())}))
    swap_in(con, ["g_works", "g_editions", "g_series", "g_members", "g_aliases",
                  "g_decisions", "g_imprints", "g_author_clusters"])
