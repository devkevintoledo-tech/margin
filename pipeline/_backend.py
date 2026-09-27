"""The backend's pure identity rules, importable without the app.

The pipeline must group works exactly as the app does, so it reuses the rule
modules rather than copying them. Only modules with no I/O and no settings are
re-exported here; importing anything else from ``app`` would drag in the
database configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.series_identity import (  # noqa: E402
    SUBJECT_SEPARATOR,
    choose_container,
    join_subjects,
    parse_tags,
    series_key,
    slugify,
    tag_name,
)
from app.services.text import normalize  # noqa: E402
from app.services.work_identity import (  # noqa: E402
    canonical_key,
    classify_kind,
    clean_title,
    display_title,
    normalize_isbn,
)

__all__ = [
    "SUBJECT_SEPARATOR",
    "canonical_key",
    "choose_container",
    "classify_kind",
    "clean_title",
    "display_title",
    "join_subjects",
    "normalize",
    "normalize_isbn",
    "parse_tags",
    "series_key",
    "slugify",
    "tag_name",
]
