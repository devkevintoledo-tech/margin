"""The release contract: the Parquet schemas production loads (spec §4.5).

The other half is ``COLUMNS`` in ``backend/app/services/catalog_loader.py``;
``backend/tests/test_catalog_contract.py`` fails if the two drift. Changing a
column means bumping ``SCHEMA_VERSION`` and teaching the
loader the new version. Deliberately pyarrow-only, so the backend's test can
import it without the pipeline's other dependencies.
"""

from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = 1

_S, _I32, _I64, _F64 = pa.string(), pa.int32(), pa.int64(), pa.float64()
SCHEMAS = {
    "works": pa.schema([
        ("id", _S), ("ol_work_id", _S), ("canonical_key", _S), ("title", _S), ("subtitle", _S),
        ("author", _S), ("first_publish_year", _I32), ("kind", _S), ("series_id", _S),
        ("ol_cover_id", _I64), ("ol_edition_count", _I32), ("readinglog_count", _I32),
        ("ratings_count", _I32), ("subjects", _S), ("representative_edition_id", _S),
    ]),
    "editions": pa.schema([
        ("id", _S), ("ol_edition_id", _S), ("work_id", _S), ("title", _S), ("subtitle", _S),
        ("author", _S), ("publisher", _S), ("published_year", _I32), ("isbn_13", _S),
        ("page_count", _I32), ("cover_url", _S), ("language", _S),
    ]),
    "series": pa.schema([
        ("id", _S), ("key", _S), ("source", _S), ("provenance", _S), ("name", _S), ("slug", _S),
        ("canonical_key", _S), ("kind", _S), ("parent_series_id", _S),
    ]),
    "series_members": pa.schema([
        ("series_id", _S), ("work_id", _S), ("position", _F64), ("provenance", _S), ("confidence", _S),
    ]),
    "work_aliases": pa.schema([("ol_work_id", _S), ("work_id", _S)]),
}
