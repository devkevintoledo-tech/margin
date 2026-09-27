"""Paths, source URLs and the build context every stage receives."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import duckdb

from pipeline.contract import SCHEMA_VERSION  # noqa: F401  (re-exported for stages)

REPO = Path(__file__).resolve().parents[1]
PIPELINE_DIR = REPO / "pipeline"

# Never change: every release id is derived from it, so a new namespace would
# give every book a new UUID and orphan every thread and shelf.
MARGIN_NS = uuid.UUID("7c1d0a4e-3b5f-4e2a-9d6c-8f4b2a1e0c37")
STAGES = ("fetch", "select", "extract", "group", "publish")

_OL_DATA = "https://openlibrary.org/data"
OL_DUMPS = {
    "ratings": f"{_OL_DATA}/ol_dump_ratings_latest.txt.gz",
    "reading_log": f"{_OL_DATA}/ol_dump_reading-log_latest.txt.gz",
    "works": f"{_OL_DATA}/ol_dump_works_latest.txt.gz",
    "authors": f"{_OL_DATA}/ol_dump_authors_latest.txt.gz",
    "editions": f"{_OL_DATA}/ol_dump_editions_latest.txt.gz",
}
WIKIDATA_SPARQL_URL = os.environ.get("WIKIDATA_SPARQL_URL", "https://query.wikidata.org/sparql")
USER_AGENT = "MARGIN-catalog-pipeline/1.0 (https://github.com/devkevintoledo-tech/margin)"


@dataclass
class BuildContext:
    build_dir: Path
    con: duckdb.DuckDBPyConnection
    ol_dumps: dict[str, str] = field(default_factory=lambda: dict(OL_DUMPS))
    sparql_url: str = WIKIDATA_SPARQL_URL
    rules_dir: Path = PIPELINE_DIR / "rules"
    overrides_dir: Path = PIPELINE_DIR / "overrides"
    golden_path: Path = PIPELINE_DIR / "golden" / "series.yaml"
    releases_dir: Path = REPO / "releases"
    version: str | None = None
    upload: bool = False
    sleep: Callable[[float], None] = time.sleep

    @property
    def raw_dir(self) -> Path:
        return self.build_dir / "raw"
