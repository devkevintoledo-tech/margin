"""select (spec §4.2): keep read works that have an English edition and are not junk."""

from __future__ import annotations

import json

import pyarrow as pa

from pipeline.config import BuildContext
from pipeline.db import iter_rows, swap_in, write_table
from pipeline.select_rules import JunkRules, WorkForSelect
from pipeline.sources.ol_records import author_ids, strings, text


def run(ctx: BuildContext) -> None:
    con = ctx.con
    rules = JunkRules.load(ctx.rules_dir / "junk.yaml")
    english = {
        work: (pages, tuple(p for p in publishers if p))
        for work, pages, publishers in con.execute("""
            SELECT work_ol_id, max(number_of_pages), flatten(list(publishers))
            FROM raw_editions WHERE is_english AND work_ol_id IS NOT NULL GROUP BY work_ol_id
        """).fetchall()
    }
    kept: list[str] = []
    dropped: list[tuple[str, str]] = []
    for ol_id, blob in iter_rows(con, "SELECT ol_id, json FROM raw_works ORDER BY ol_id"):
        if ol_id not in english:
            dropped.append((ol_id, "not_english"))
            continue
        record = json.loads(blob)
        pages, publishers = english[ol_id]
        reason = rules.reason(WorkForSelect(
            ol_id=ol_id, title=text(record.get("title")) or "", subjects=tuple(strings(record.get("subjects"))),
            author_ids=tuple(author_ids(record)), max_pages=pages, publishers=publishers))
        if reason is None:
            kept.append(ol_id)
        else:
            dropped.append((ol_id, reason))
    write_table(con, "selected", pa.table({"ol_id": pa.array(kept, pa.string())}))
    write_table(con, "select_drops", pa.table({
        "ol_id": pa.array([d[0] for d in dropped], pa.string()),
        "rule": pa.array([d[1] for d in dropped], pa.string())}))
    swap_in(con, ["selected", "select_drops"])
