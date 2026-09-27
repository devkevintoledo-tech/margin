"""Deterministic row ids and slugs (spec §4.6).

The same book gets the same UUID in every environment and every release,
which is what lets a new release update rows in place under live threads.
"""

from __future__ import annotations

import uuid
from typing import Mapping

from pipeline._backend import slugify
from pipeline.config import MARGIN_NS


def row_id(identity: str) -> str:
    return str(uuid.uuid5(MARGIN_NS, identity))


def work_identity(ol_id: str) -> str:
    return f"work:ol:{ol_id}"


def edition_identity(ol_id: str) -> str:
    return f"edition:ol:{ol_id}"


def series_identity(key: str) -> str:
    """``key`` is ``wd:Q45875``, ``ol:<series_key>`` or ``single:OL27448W``."""
    return f"series:{key}"


def assign_slugs(names: Mapping[str, str]) -> dict[str, str]:
    """Map each identity to a unique slug of its name.

    Identities sharing a slug base are sorted; the first keeps the bare base
    and the rest take ``-2``, ``-3``… skipping any suffix that is itself some
    other name's base, so "Dune" and "Dune 2" never collide.
    """
    by_base: dict[str, list[str]] = {}
    for identity in sorted(names):
        by_base.setdefault(slugify(names[identity]), []).append(identity)
    taken = set(by_base)
    slugs: dict[str, str] = {}
    for base in sorted(by_base):
        first, *rest = by_base[base]
        slugs[first] = base
        n = 2
        for identity in rest:
            while f"{base}-{n}" in taken:
                n += 1
            slugs[identity] = f"{base}-{n}"
            taken.add(slugs[identity])
    return slugs
