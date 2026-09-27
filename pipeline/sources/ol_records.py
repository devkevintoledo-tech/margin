"""Reading fields out of Open Library JSON records, defensively.

Dump records span twenty years of schema drift: authors appear as
``{"author": {"key": …}}`` or bare ``{"key": …}``, dates are free text.
"""

from __future__ import annotations

import re

_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_AUTHOR_KEY = re.compile(r"OL[0-9]+A")


def year_of(text) -> int | None:
    match = _YEAR.search(text) if isinstance(text, str) else None
    return int(match.group(1)) if match else None


def author_ids(record: dict) -> list[str]:
    """The work's author ids, in listed order, without duplicates."""
    found: list[str] = []
    for entry in record.get("authors") or []:
        if not isinstance(entry, dict):
            continue
        ref = entry.get("author", entry)
        key = ref.get("key") if isinstance(ref, dict) else None
        match = _AUTHOR_KEY.search(key) if isinstance(key, str) else None
        if match and match.group() not in found:
            found.append(match.group())
    return found


def strings(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def text(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None
