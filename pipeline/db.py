"""DuckDB helpers: the build database and the stage-swap discipline.

A stage writes only ``tmp_<name>`` tables and calls :func:`swap_in` once it
has finished, so a crash leaves the previous stage's tables untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import duckdb
import pyarrow as pa

TMP_PREFIX = "tmp_"


def connect(build_dir: Path) -> duckdb.DuckDBPyConnection:
    build_dir.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(build_dir / "catalog.duckdb"))


def sql_path(path: Path) -> str:
    """A filesystem path as a quoted SQL string literal."""
    return "'" + str(path).replace("'", "''") + "'"


def table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}


def drop_temp_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Remove what a crashed stage left behind."""
    for name in sorted(table_names(con)):
        if name.startswith(TMP_PREFIX):
            con.execute(f'DROP TABLE "{name}"')


def write_table(con: duckdb.DuckDBPyConnection, name: str, table: pa.Table) -> None:
    """Materialize an Arrow table as ``tmp_<name>``."""
    con.register("_incoming", table)
    try:
        con.execute(f'CREATE OR REPLACE TABLE "{TMP_PREFIX}{name}" AS SELECT * FROM _incoming')
    finally:
        con.unregister("_incoming")


def swap_in(con: duckdb.DuckDBPyConnection, names: Iterable[str]) -> None:
    """Replace each table with its ``tmp_`` twin, all or nothing."""
    con.execute("BEGIN TRANSACTION")
    try:
        for name in names:
            con.execute(f'DROP TABLE IF EXISTS "{name}"')
            con.execute(f'ALTER TABLE "{TMP_PREFIX}{name}" RENAME TO "{name}"')
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def iter_rows(con: duckdb.DuckDBPyConnection, sql: str, params=None, batch: int = 10_000):
    """Stream a query's rows without materializing the whole result in Python."""
    cursor = con.execute(sql, params or [])
    while rows := cursor.fetchmany(batch):
        yield from rows
