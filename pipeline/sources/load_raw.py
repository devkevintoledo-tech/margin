"""Load the downloaded dumps into ``tmp_raw_*`` tables with DuckDB.

DuckDB reads the gzipped TSVs directly, so the works and authors dumps are
filtered in SQL rather than parsed line by line in Python.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Mapping

import duckdb
import pyarrow as pa

from pipeline.db import TMP_PREFIX, sql_path
from pipeline.sources.editions import EDITION_SCHEMA

# The OL entity dumps: type, key, revision, last_modified, JSON. No quoting:
# the JSON column is full of double quotes.
_ENTITY_TSV = (
    "delim='\t', header=false, quote='', escape='', compression='gzip', "
    "max_line_size=20000000, "
    "columns={'type': 'VARCHAR', 'key': 'VARCHAR', 'revision': 'VARCHAR', "
    "'modified': 'VARCHAR', 'json': 'VARCHAR'}"
)
# Ratings and reading-log dumps: work key, edition key, value, date.
_LOG_TSV = (
    "delim='\t', header=false, quote='', escape='', compression='gzip', null_padding=true, "
    "columns={'work': 'VARCHAR', 'edition': 'VARCHAR', 'value': 'VARCHAR', 'date': 'VARCHAR'}"
)
_MAX_HOPS = 5


def resolver(redirects: Mapping[str, str]) -> Callable[[str], str]:
    """Follow OL redirects (merged records) to the surviving id."""
    def resolve(ol_id: str) -> str:
        seen = {ol_id}
        for _ in range(_MAX_HOPS):
            target = redirects.get(ol_id)
            if target is None or target in seen:
                break
            ol_id = target
            seen.add(target)
        return ol_id
    return resolve


def load_redirects(con: duckdb.DuckDBPyConnection, dump: Path, table: str, suffix: str) -> dict[str, str]:
    """``tmp_<table>(from_ol, to_ol)`` for every redirect record; returned as a dict."""
    pattern = f"OL[0-9]+{suffix}"
    con.execute(f"""
        CREATE OR REPLACE TABLE {TMP_PREFIX}{table} AS
        SELECT regexp_extract(key, '{pattern}') AS from_ol,
               regexp_extract(json_extract_string(json, '$.location'), '{pattern}') AS to_ol
        FROM read_csv({sql_path(dump)}, {_ENTITY_TSV})
        WHERE type = '/type/redirect' AND to_ol <> '' AND from_ol <> ''
    """)
    return dict(con.execute(f"SELECT from_ol, to_ol FROM {TMP_PREFIX}{table}").fetchall())


def load_popularity(con: duckdb.DuckDBPyConnection, ratings: Path, reading_log: Path,
                    resolve: Callable[[str], str]) -> set[str]:
    """``tmp_raw_popularity(ol_id, ratings_count, readinglog_count)``, keyed by surviving id.

    Returns the raw ids seen, redirected or not — the read set's seed.
    """
    raw = con.execute(f"""
        SELECT ol_id, sum(r)::INTEGER, sum(l)::INTEGER FROM (
            SELECT regexp_extract(work, 'OL[0-9]+W') AS ol_id, 1 AS r, 0 AS l
            FROM read_csv({sql_path(ratings)}, {_LOG_TSV})
            UNION ALL
            SELECT regexp_extract(work, 'OL[0-9]+W'), 0, 1
            FROM read_csv({sql_path(reading_log)}, {_LOG_TSV})
        ) WHERE ol_id <> '' GROUP BY ol_id
    """).fetchall()
    totals: dict[str, list[int]] = {}
    for ol_id, ratings_count, logs in raw:
        entry = totals.setdefault(resolve(ol_id), [0, 0])
        entry[0] += ratings_count
        entry[1] += logs
    ids = sorted(totals)
    con.register("_pop", pa.table({
        "ol_id": ids,
        "ratings_count": pa.array([totals[i][0] for i in ids], pa.int32()),
        "readinglog_count": pa.array([totals[i][1] for i in ids], pa.int32()),
    }))
    con.execute(f"CREATE OR REPLACE TABLE {TMP_PREFIX}raw_popularity AS SELECT * FROM _pop")
    con.unregister("_pop")
    return {row[0] for row in raw}


def load_entities(con: duckdb.DuckDBPyConnection, dump: Path, table: str, type_: str,
                  suffix: str, ids: Iterable[str]) -> None:
    """``tmp_<table>(ol_id, json)`` for the records of ``type_`` whose id is in ``ids``."""
    con.register("_ids", pa.table({"ol_id": sorted(set(ids))}))
    con.execute(f"""
        CREATE OR REPLACE TABLE {TMP_PREFIX}{table} AS
        SELECT regexp_extract(key, 'OL[0-9]+{suffix}') AS ol_id, json
        FROM read_csv({sql_path(dump)}, {_ENTITY_TSV})
        WHERE type = '{type_}' AND regexp_extract(key, 'OL[0-9]+{suffix}') IN (SELECT ol_id FROM _ids)
    """)
    con.unregister("_ids")


class DuckSink:
    """Where the editions stream lands: ``tmp_raw_editions``."""

    def __init__(self, con: duckdb.DuckDBPyConnection, table: str = "raw_editions") -> None:
        self.con, self.table = con, f"{TMP_PREFIX}{table}"

    def reset(self) -> None:
        self.con.register("_empty", EDITION_SCHEMA.empty_table())
        self.con.execute(f"CREATE OR REPLACE TABLE {self.table} AS SELECT * FROM _empty")
        self.con.unregister("_empty")

    def write(self, batch: pa.Table) -> None:
        self.con.register("_batch", batch)
        self.con.execute(f"INSERT INTO {self.table} SELECT * FROM _batch")
        self.con.unregister("_batch")
