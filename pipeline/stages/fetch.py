"""fetch (spec §4.1): download, pull Wikidata, stream editions, load raw tables."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import httpx
import pyarrow as pa

from pipeline.config import USER_AGENT, BuildContext
from pipeline.db import TMP_PREFIX, swap_in, write_table
from pipeline.sources import load_raw, wikidata
from pipeline.sources.editions import stream_editions
from pipeline.sources.ol_dumps import download
from pipeline.sources.records import SourceRecord

TABLES = (
    "raw_popularity", "raw_work_redirects", "raw_work_aliases", "raw_editions",
    "raw_edition_counts", "raw_works", "raw_author_redirects", "raw_authors",
    "wd_memberships", "wd_series", "wd_author_ids", "wd_author_names", "sources",
)


def _wikidata_record(url: str, *parts) -> SourceRecord:
    blob = json.dumps(parts, sort_keys=True, default=list).encode()
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return SourceRecord("wikidata", url, stamp, len(blob), hashlib.sha256(blob).hexdigest())


def run(ctx: BuildContext) -> None:
    con, raw = ctx.con, ctx.raw_dir
    raw.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(60.0, read=300.0)
    with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        records = [
            download(client, name, ctx.ol_dumps[name], raw / f"{name}.txt.gz", sleep=ctx.sleep)
            for name in ("ratings", "reading_log", "works", "authors")
        ]

        memberships = wikidata.fetch_memberships(client, ctx.sparql_url, sleep=ctx.sleep)
        series = wikidata.fetch_series(client, ctx.sparql_url, {m.series for m, _ in memberships}, sleep=ctx.sleep)
        author_ids = wikidata.fetch_author_ids(client, ctx.sparql_url, sleep=ctx.sleep)

        # The read set: works someone has rated or shelved, plus Wikidata's books.
        redirects = load_raw.load_redirects(con, raw / "works.txt.gz", "raw_work_redirects", "W")
        resolve = load_raw.resolver(redirects)
        seen = load_raw.load_popularity(con, raw / "ratings.txt.gz", raw / "reading_log.txt.gz", resolve)
        wd_works = {ol for _, ol in memberships if ol.endswith("W")}
        wd_editions = {ol for _, ol in memberships if ol.endswith("M")}
        candidates = {resolve(ol) for ol in seen | wd_works}
        aliases = sorted((ol, resolve(ol)) for ol in seen | wd_works if resolve(ol) != ol)
        write_table(con, "raw_work_aliases", pa.table({
            "from_ol": [a for a, _ in aliases], "to_ol": [b for _, b in aliases]}, schema=pa.schema(
            [("from_ol", pa.string()), ("to_ol", pa.string())])))

        resolved = {k: resolve(k) for k in redirects}
        edition_record, counts = stream_editions(
            client, ctx.ol_dumps["editions"], candidates, wd_editions,
            load_raw.DuckSink(con), resolve=resolved, sleep=ctx.sleep)
        records.append(edition_record)
        ids = sorted(counts)
        write_table(con, "raw_edition_counts", pa.table({
            "ol_id": pa.array(ids, pa.string()), "edition_count": pa.array([counts[i] for i in ids], pa.int32())}))
        candidates |= {w for (w,) in con.execute(
            f"SELECT DISTINCT work_ol_id FROM {TMP_PREFIX}raw_editions "
            f"WHERE work_ol_id IS NOT NULL AND list_contains(?, ol_id)", [sorted(wd_editions)]).fetchall()}

        load_raw.load_entities(con, raw / "works.txt.gz", "raw_works", "/type/work", "W", candidates)
        author_redirects = load_raw.load_redirects(con, raw / "authors.txt.gz", "raw_author_redirects", "A")
        resolve_author = load_raw.resolver(author_redirects)
        referenced = {resolve_author(a) for (a,) in con.execute(
            f"SELECT DISTINCT unnest(regexp_extract_all(json, 'OL[0-9]+A')) FROM {TMP_PREFIX}raw_works").fetchall()}
        load_raw.load_entities(con, raw / "authors.txt.gz", "raw_authors", "/type/author", "A", referenced)

        wd_author_items = sorted({q for q, ol in author_ids if resolve_author(ol) in referenced})
        names = wikidata.fetch_author_names(client, ctx.sparql_url, wd_author_items, sleep=ctx.sleep)
        records.append(_wikidata_record(ctx.sparql_url, sorted((m.item, m.series, m.ordinal or "", ol) for m, ol in memberships),
                                        sorted(series), author_ids, names))

    write_table(con, "wd_memberships", pa.table({
        "item": pa.array([m.item for m, _ in memberships], pa.string()),
        "series": pa.array([m.series for m, _ in memberships], pa.string()),
        "ordinal": pa.array([m.ordinal for m, _ in memberships], pa.string()),
        "ol_id": pa.array([ol for _, ol in memberships], pa.string()),
    }))
    keys = sorted(series)
    write_table(con, "wd_series", pa.table({
        "qid": pa.array(keys, pa.string()),
        "label": pa.array([series[k].label for k in keys], pa.string()),
        "aliases": pa.array([list(series[k].aliases) for k in keys], pa.list_(pa.string())),
        "parents": pa.array([list(series[k].parents) for k in keys], pa.list_(pa.string())),
    }))
    write_table(con, "wd_author_ids", pa.table({
        "qid": pa.array([q for q, _ in author_ids], pa.string()),
        "ol_author_id": pa.array([ol for _, ol in author_ids], pa.string())}))
    write_table(con, "wd_author_names", pa.table({
        "qid": pa.array([q for q, _ in names], pa.string()),
        "name": pa.array([n for _, n in names], pa.string())}))
    write_table(con, "sources", pa.Table.from_pylist([r.__dict__ for r in records], schema=pa.schema([
        ("name", pa.string()), ("url", pa.string()), ("retrieved", pa.string()),
        ("size", pa.int64()), ("sha256", pa.string())])))
    swap_in(con, TABLES)
