"""The genre taxonomy and subject → genre inference (spec 2026-09-29 §5–6).

Pure: PyYAML and the stdlib only. No settings, HTTP or ORM, so the offline
catalog pipeline can import it later (tests/test_pure_imports.py enforces it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import yaml

from app.services.text import normalize

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "genres.yaml"

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_KEYS = {"slug", "name", "description", "match", "exclude", "children"}
# OL tags like `series:`, `place:`, `person:`, `nyt:` name things, not genres.
_PREFIX = re.compile(r"^\s*[a-z_]+\s*:", re.IGNORECASE)
_GENRE_PREFIX = re.compile(r"^\s*genre\s*:", re.IGNORECASE)


class TaxonomyError(ValueError):
    """The taxonomy file is malformed; nothing is written."""


@dataclass(frozen=True)
class GenreEntry:
    slug: str
    name: str
    description: str | None
    parent: str | None
    position: int
    match: tuple[str, ...]
    exclude: tuple[str, ...]


@dataclass(frozen=True)
class Taxonomy:
    entries: tuple[GenreEntry, ...]

    def by_slug(self) -> dict[str, GenreEntry]:
        return {e.slug: e for e in self.entries}

    def slugs(self) -> set[str]:
        return {e.slug for e in self.entries}


def _phrases(raw: dict, key: str, slug: str) -> tuple[str, ...]:
    values = raw.get(key, [])
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise TaxonomyError(f"{slug}: {key} must be a list of strings")
    cleaned = tuple(normalize(v) for v in values)
    if any(not v for v in cleaned):
        raise TaxonomyError(f"{slug}: empty {key.rstrip('e')} phrase")
    return cleaned


def parse_taxonomy(data: object) -> Taxonomy:
    """Validate and flatten the YAML structure. Raises TaxonomyError."""
    if not isinstance(data, list) or not data:
        raise TaxonomyError("the taxonomy must be a non-empty list")
    entries: list[GenreEntry] = []
    seen: set[str] = set()

    def visit(raw: object, parent: str | None, position: int) -> None:
        if not isinstance(raw, dict):
            raise TaxonomyError(f"entry {raw!r} is not a mapping")
        slug = raw.get("slug")
        if not isinstance(slug, str) or not _SLUG.match(slug):
            raise TaxonomyError(f"bad slug {slug!r}")
        unknown = set(raw) - _KEYS
        if unknown:
            raise TaxonomyError(f"{slug}: unknown keys {sorted(unknown)}")
        if slug in seen:
            raise TaxonomyError(f"duplicate slug {slug}")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise TaxonomyError(f"{slug} needs a name")
        seen.add(slug)
        entries.append(GenreEntry(
            slug=slug, name=name.strip(), description=raw.get("description"), parent=parent,
            position=position, match=_phrases(raw, "match", slug), exclude=_phrases(raw, "exclude", slug),
        ))
        children = raw.get("children", [])
        if not isinstance(children, list):
            raise TaxonomyError(f"{slug}: children must be a list")
        if children and parent is not None:
            raise TaxonomyError(f"{slug}: a subgenre cannot have subgenres")
        for i, child in enumerate(children):
            visit(child, slug, i)

    for i, raw in enumerate(data):
        visit(raw, None, i)
    return Taxonomy(tuple(entries))


def load_taxonomy(path: Path = TAXONOMY_PATH) -> Taxonomy:
    return parse_taxonomy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def shipped_taxonomy() -> Taxonomy:
    """The taxonomy the app ships. Cached: the file only changes with a deploy."""
    return load_taxonomy()


def _has(haystack: str, needle: str) -> bool:
    # Both sides are normalize()d: lowercase words separated by single spaces,
    # so padding with spaces gives word-boundary matching ("crime" ∉ "crimea").
    return f" {needle} " in f" {haystack} "


def _matches(pool: list[str], taxonomy: Taxonomy) -> set[str]:
    found: set[str] = set()
    for entry in taxonomy.entries:
        for subject in pool:
            if any(_has(subject, x) for x in entry.exclude):
                continue
            if any(_has(subject, n) for n in entry.match):
                found.add(entry.slug)
                break
    return found


def infer_genres(subjects: Sequence[str], taxonomy: Taxonomy) -> set[str]:
    """Genre slugs a work's subjects (or Google categories) imply.

    Explicit ``genre:`` tags are matched first, and plain subjects only when
    they matched nothing. Other prefixed tags (``series:``, ``place:``…) never
    count. Every match is kept; there is no generic fallback.
    """
    explicit = [normalize(_GENRE_PREFIX.sub("", s)) for s in subjects if _GENRE_PREFIX.match(s)]
    plain = [normalize(s) for s in subjects if not _PREFIX.match(s)]
    for pool in (explicit, plain):
        found = _matches([s for s in pool if s], taxonomy)
        if found:
            return found
    return set()
