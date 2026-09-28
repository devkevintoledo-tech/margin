"""The loader reads exactly what the pipeline writes (pipeline/contract.py)."""

import sys
from pathlib import Path

import pyarrow as pa
import pytest

from app.services.catalog_loader import COLUMNS, SCHEMA_VERSION

REPO = Path(__file__).resolve().parents[2]
ARROW_FOR = {"uuid": pa.string(), "text": pa.string(), "int": pa.int32(), "bigint": pa.int64(), "numeric": pa.float64()}


def _pipeline_contract():
    if not (REPO / "pipeline" / "contract.py").exists():
        # Inside the backend container only backend/ is mounted; CI checks out everything.
        pytest.skip("pipeline/ is not present next to backend/")
    sys.path.insert(0, str(REPO))
    try:
        from pipeline import contract
    finally:
        sys.path.remove(str(REPO))
    return contract.SCHEMA_VERSION, contract.SCHEMAS


def test_loader_columns_match_the_pipeline_schemas():
    version, schemas = _pipeline_contract()
    assert version == SCHEMA_VERSION
    assert set(schemas) == set(COLUMNS)
    for name, columns in COLUMNS.items():
        assert [(f.name, f.type) for f in schemas[name]] == [(c, ARROW_FOR[t]) for c, t in columns], name
