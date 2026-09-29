"""Load a catalog release into the app database (spec §6.2).

A release is a folder of Parquet files written by the offline pipeline
(``pipeline/release.py`` holds the other half of this contract). Loading runs
in the caller's transaction, so any failure rolls everything back:

1. verify checksums and schema version; refuse an older release;
2. COPY each file into a temp staging table;
3. re-slug runtime series a release slug collides with, and free the
   ``(source, external_id)`` of runtime works the release adopts;
4. upsert series, works, editions, parents, members and aliases by id;
5. carry tagged threads when a book changes rooms, adopt runtime works
   (``merge_works``), retire the runtime rooms that emptied, and settle rows
   the new release no longer contains.

Loading the same release twice is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogRelease, Work
from app.services import genres as genres_service
from app.services.genre_inference import infer_genres, shipped_taxonomy
from app.services.series_identity import SUBJECT_SEPARATOR
from app.services.works import merge_works

SCHEMA_VERSION = 1
_VERSION = re.compile(r"^(\d{4})\.(\d{2})\.(\d+)$")

# Staging columns, in Parquet order, with the SQL type each is staged as.
# Mirrors pipeline/release.py SCHEMAS; the loader refuses a file that differs.
COLUMNS: dict[str, list[tuple[str, str]]] = {
    "works": [
        ("id", "uuid"), ("ol_work_id", "text"), ("canonical_key", "text"), ("title", "text"),
        ("subtitle", "text"), ("author", "text"), ("first_publish_year", "int"), ("kind", "text"),
        ("series_id", "uuid"), ("ol_cover_id", "bigint"), ("ol_edition_count", "int"),
        ("readinglog_count", "int"), ("ratings_count", "int"), ("subjects", "text"),
        ("representative_edition_id", "uuid"),
    ],
    "editions": [
        ("id", "uuid"), ("ol_edition_id", "text"), ("work_id", "uuid"), ("title", "text"),
        ("subtitle", "text"), ("author", "text"), ("publisher", "text"), ("published_year", "int"),
        ("isbn_13", "text"), ("page_count", "int"), ("cover_url", "text"), ("language", "text"),
    ],
    "series": [
        ("id", "uuid"), ("key", "text"), ("source", "text"), ("provenance", "text"), ("name", "text"),
        ("slug", "text"), ("canonical_key", "text"), ("kind", "text"), ("parent_series_id", "uuid"),
    ],
    "series_members": [
        ("series_id", "uuid"), ("work_id", "uuid"), ("position", "numeric"), ("provenance", "text"),
        ("confidence", "text"),
    ],
    "work_aliases": [("ol_work_id", "text"), ("work_id", "uuid")],
}
_BATCH = 50_000


class CatalogLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    path: Path
    manifest: dict

    @property
    def version(self) -> str:
        return self.manifest["version"]


@dataclass
class LoadStats:
    version: str
    noop: bool = False
    rows: dict[str, int] = field(default_factory=dict)
    reslugged: int = 0
    adopted: int = 0
    retired_series: int = 0
    moved_threads: int = 0
    deleted_works: int = 0
    kept_works: int = 0
    deleted_series: int = 0


def version_key(version: str) -> tuple[int, int, int]:
    match = _VERSION.match(version)
    if not match:
        raise CatalogLoadError(f"bad release version {version!r}")
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def read_release(path: Path) -> Release:
    """Open a release folder, verifying every checksum and the schema version."""
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise CatalogLoadError(f"{path} has no manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CatalogLoadError(
            f"release schema {manifest.get('schema_version')} is not {SCHEMA_VERSION}; upgrade the loader")
    version_key(manifest.get("version", ""))
    for name, expected in manifest["files"].items():
        file = path / name
        if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise CatalogLoadError(f"{name} is missing or does not match its checksum")
    for name, columns in COLUMNS.items():
        actual = pq.read_schema(path / f"{name}.parquet").names
        if actual != [c for c, _ in columns]:
            raise CatalogLoadError(f"{name}.parquet columns {actual} do not match the contract")
    return Release(path, manifest)


def _convert(kind: str, value):
    if value is None:
        return None
    return uuid.UUID(value) if kind == "uuid" else value


async def _stage(db: AsyncSession, release: Release) -> dict[str, int]:
    connection = await db.connection()
    raw = (await connection.get_raw_connection()).driver_connection
    counts = {}
    taxonomy = shipped_taxonomy()
    for name, columns in COLUMNS.items():
        extra = [("genre_slugs", "text[]")] if name == "works" else []
        ddl = ", ".join(f"{c} {t}" for c, t in columns + extra)
        await db.execute(text(f"DROP TABLE IF EXISTS stage_{name}"))
        await db.execute(text(f"CREATE TEMP TABLE stage_{name} ({ddl}) ON COMMIT DROP"))
        counts[name] = 0
        for batch in pq.ParquetFile(release.path / f"{name}.parquet").iter_batches(batch_size=_BATCH):
            records = []
            for row in batch.to_pylist():
                record = [_convert(t, row[c]) for c, t in columns]
                if name == "works":
                    subjects = (row["subjects"] or "").split(SUBJECT_SEPARATOR)
                    record.append(sorted(infer_genres([s for s in subjects if s], taxonomy)))
                records.append(tuple(record))
            await raw.copy_records_to_table(
                f"stage_{name}", records=records, columns=[c for c, _ in columns + extra])
            counts[name] += len(records)
    for name in COLUMNS:
        await db.execute(text(f"ANALYZE stage_{name}"))
    return counts


async def _reslug_collisions(db: AsyncSession) -> int:
    """Release slugs win. A different series holding one moves to ``<slug>-N``."""
    rows = (await db.execute(text("""
        SELECT s.id, s.slug FROM series s JOIN stage_series t ON t.slug = s.slug
        WHERE s.id <> t.id ORDER BY s.slug"""))).all()
    for series_id, slug in rows:
        taken = set((await db.execute(text(
            "SELECT slug FROM series WHERE slug LIKE :p UNION SELECT slug FROM stage_series WHERE slug LIKE :p"),
            {"p": f"{slug}-%"})).scalars())
        n = 2
        while f"{slug}-{n}" in taken:
            n += 1
        await db.execute(text("UPDATE series SET slug = :new WHERE id = :id"), {"new": f"{slug}-{n}", "id": series_id})
    return len(rows)


async def _adoptions(db: AsyncSession) -> dict[uuid.UUID, uuid.UUID]:
    """Runtime works (``catalog_release IS NULL``) that are release works: ``{runtime id: release id}``.

    By Open Library id, directly or through an alias; a heuristic work by its
    ``canonical_key`` when exactly one release work carries that key (the key
    embeds the primary author, so this is title plus author).
    """
    rows = (await db.execute(text("""
        SELECT w.id, coalesce(t.id, a.work_id) FROM works w
        LEFT JOIN stage_works t ON t.ol_work_id = w.external_id
        LEFT JOIN stage_work_aliases a ON a.ol_work_id = w.external_id
        WHERE w.catalog_release IS NULL AND w.merged_into_id IS NULL AND w.source = 'openlibrary'
          AND coalesce(t.id, a.work_id) IS NOT NULL
        UNION ALL
        SELECT w.id, t.id FROM works w
        JOIN (SELECT canonical_key, min(id::text)::uuid AS id FROM stage_works
              GROUP BY canonical_key HAVING count(*) = 1) t ON t.canonical_key = w.canonical_key
        WHERE w.catalog_release IS NULL AND w.merged_into_id IS NULL AND w.source = 'heuristic'
    """))).all()
    adoptions = {runtime: target for runtime, target in rows}
    if adoptions:
        # Frees uq_works_source_external_id for the release row. The tombstone
        # still resolves by id; nothing looks a tombstone up by external id.
        await db.execute(text("""
            UPDATE works SET external_id = 'merged:' || replace(id::text, '-', '')
            WHERE id = ANY(:ids)"""), {"ids": list(adoptions)})
    return adoptions


_UPSERTS = (
    """INSERT INTO series (id, source, external_id, name, slug, canonical_key, kind, provenance, catalog_release)
       SELECT id, source::series_source_enum, key, name, slug, canonical_key, kind::series_kind_enum,
              provenance::series_provenance_enum, :version FROM stage_series
       ON CONFLICT (id) DO UPDATE SET source = EXCLUDED.source, external_id = EXCLUDED.external_id,
           name = EXCLUDED.name, slug = EXCLUDED.slug, canonical_key = EXCLUDED.canonical_key,
           kind = EXCLUDED.kind, provenance = EXCLUDED.provenance, catalog_release = EXCLUDED.catalog_release,
           merged_into_id = NULL, updated_at = now()""",
    """INSERT INTO works (id, source, external_id, canonical_key, title, subtitle, author, first_publish_year,
                          kind, identity_provenance, series_id, ol_cover_id, ol_edition_count, readinglog_count,
                          ratings_count, subjects, catalog_release)
       SELECT t.id, 'openlibrary', t.ol_work_id, t.canonical_key, t.title, t.subtitle, t.author,
              t.first_publish_year, t.kind::work_kind_enum, 'isbn', t.series_id, t.ol_cover_id,
              t.ol_edition_count, t.readinglog_count, t.ratings_count, t.subjects, :version
       FROM stage_works t
       ON CONFLICT (id) DO UPDATE SET external_id = EXCLUDED.external_id, canonical_key = EXCLUDED.canonical_key,
           title = EXCLUDED.title, subtitle = EXCLUDED.subtitle, author = EXCLUDED.author,
           first_publish_year = EXCLUDED.first_publish_year, kind = EXCLUDED.kind, series_id = EXCLUDED.series_id,
           ol_cover_id = EXCLUDED.ol_cover_id, ol_edition_count = EXCLUDED.ol_edition_count,
           readinglog_count = EXCLUDED.readinglog_count, ratings_count = EXCLUDED.ratings_count,
           subjects = EXCLUDED.subjects,
           catalog_release = EXCLUDED.catalog_release, merged_into_id = NULL, updated_at = now()""",
    """INSERT INTO books (id, source, external_id, title, subtitle, author, cover_url, publisher,
                          published_year, isbn_13, page_count, language, work_id)
       SELECT id, 'openlibrary', ol_edition_id, title, subtitle, author, cover_url, publisher,
              published_year, isbn_13, page_count, language, work_id FROM stage_editions
       ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, subtitle = EXCLUDED.subtitle,
           author = EXCLUDED.author, cover_url = EXCLUDED.cover_url, publisher = EXCLUDED.publisher,
           published_year = EXCLUDED.published_year, isbn_13 = EXCLUDED.isbn_13,
           page_count = EXCLUDED.page_count, language = EXCLUDED.language, work_id = EXCLUDED.work_id""",
    # Enrichment may have picked a better representative since; keep it.
    """UPDATE works w SET representative_book_id = t.representative_edition_id
       FROM stage_works t WHERE w.id = t.id AND w.representative_book_id IS NULL
         AND t.representative_edition_id IS NOT NULL""",
    """UPDATE series s SET parent_series_id = t.parent_series_id
       FROM stage_series t WHERE s.id = t.id AND s.parent_series_id IS DISTINCT FROM t.parent_series_id""",
    """DELETE FROM series_members m USING series s
       WHERE m.series_id = s.id AND s.catalog_release IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM stage_series_members t WHERE t.series_id = m.series_id AND t.work_id = m.work_id)""",
    """INSERT INTO series_members (series_id, work_id, position, provenance, confidence)
       SELECT series_id, work_id, position, provenance::series_provenance_enum,
              confidence::membership_confidence_enum FROM stage_series_members
       ON CONFLICT (series_id, work_id) DO UPDATE SET position = EXCLUDED.position,
           provenance = EXCLUDED.provenance, confidence = EXCLUDED.confidence""",
    """INSERT INTO work_aliases (ol_work_id, work_id) SELECT ol_work_id, work_id FROM stage_work_aliases
       ON CONFLICT (ol_work_id) DO UPDATE SET work_id = EXCLUDED.work_id""",
)


async def retire_series(db: AsyncSession, old: uuid.UUID, survivor: uuid.UUID,
                        book: uuid.UUID | None = None) -> int:
    """Move a room's threads and remaining (tombstoned) works into ``survivor``, then tombstone it.

    ``book`` is a singleton's one work: its untagged threads were about that
    book, so they are tagged with it rather than dropped into the series feed.
    """
    if book is not None:
        await db.execute(text("UPDATE threads SET work_id = :w WHERE series_id = :old AND work_id IS NULL"),
                         {"w": book, "old": old})
    moved = (await db.execute(text("UPDATE threads SET series_id = :new WHERE series_id = :old"),
                              {"new": survivor, "old": old})).rowcount or 0
    await db.execute(text("UPDATE works SET series_id = :new WHERE series_id = :old"), {"new": survivor, "old": old})
    await db.execute(text("UPDATE series SET merged_into_id = :new, parent_series_id = NULL WHERE id = :old"),
                     {"new": survivor, "old": old})
    await db.execute(text("UPDATE series SET merged_into_id = :new WHERE merged_into_id = :old"),
                     {"new": survivor, "old": old})
    return moved


async def _merge(db: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID) -> None:
    source, target = await db.get(Work, source_id), await db.get(Work, target_id)
    if source is not None and target is not None:
        await merge_works(db, source, target)


async def _retire_emptied_rooms(db: AsyncSession, former: dict[uuid.UUID, list[uuid.UUID]]) -> tuple[int, int]:
    """A runtime room whose every book was adopted follows most of them into the release."""
    retired = moved = 0
    for old, targets in sorted(former.items()):
        still_live = await db.scalar(text(
            "SELECT count(*) FROM works WHERE series_id = :s AND merged_into_id IS NULL"), {"s": old})
        merged = await db.scalar(text("SELECT merged_into_id FROM series WHERE id = :s"), {"s": old})
        if still_live or merged is not None:
            continue
        rooms = Counter((await db.execute(text("SELECT series_id FROM works WHERE id = ANY(:ids)"),
                                          {"ids": targets})).scalars())
        survivor = min(rooms, key=lambda r: (-rooms[r], str(r)))
        moved += await retire_series(db, old, survivor)
        retired += 1
    return retired, moved


async def _settle_absent(db: AsyncSession, version: str, stats: LoadStats,
                         old_rooms: dict[uuid.UUID, uuid.UUID]) -> None:
    """Rows an earlier release loaded that this one no longer contains."""
    absent = (await db.execute(text("""
        SELECT w.id, a.work_id FROM works w LEFT JOIN stage_work_aliases a ON a.ol_work_id = w.external_id
        WHERE w.catalog_release IS NOT NULL AND w.catalog_release <> :v AND w.merged_into_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM stage_works t WHERE t.id = w.id)"""), {"v": version})).all()
    for work_id, alias_target in absent:
        if alias_target is not None:
            await _merge(db, work_id, alias_target)
            continue
        referenced = await db.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM threads WHERE work_id = :w) OR EXISTS (SELECT 1 FROM shelves WHERE work_id = :w)
        """), {"w": work_id})
        if referenced:
            stats.kept_works += 1
        else:
            # Its tombstones (runtime works it adopted) go with it: merged_into_id
            # is ON DELETE SET NULL, which would bring them back to life.
            await db.execute(text("DELETE FROM works WHERE merged_into_id = :w"), {"w": work_id})
            await db.execute(text("DELETE FROM works WHERE id = :w"), {"w": work_id})
            stats.deleted_works += 1

    gone = (await db.execute(text("""
        SELECT s.id FROM series s WHERE s.catalog_release IS NOT NULL AND s.catalog_release <> :v
          AND s.merged_into_id IS NULL AND NOT EXISTS (SELECT 1 FROM stage_series t WHERE t.id = s.id)
        ORDER BY s.id"""), {"v": version})).scalars().all()
    for series_id in gone:
        used = await db.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM works WHERE series_id = :s) OR EXISTS (SELECT 1 FROM threads WHERE series_id = :s)
        """), {"s": series_id})
        if not used:
            await db.execute(text("""
                DELETE FROM series t WHERE t.merged_into_id = :s
                  AND NOT EXISTS (SELECT 1 FROM works WHERE series_id = t.id)
                  AND NOT EXISTS (SELECT 1 FROM threads WHERE series_id = t.id)"""), {"s": series_id})
            await db.execute(text("DELETE FROM series WHERE id = :s"), {"s": series_id})
            stats.deleted_series += 1
            continue
        former = [w for w, room in old_rooms.items() if room == series_id]
        rooms = Counter((await db.execute(text("SELECT series_id FROM works WHERE id = ANY(:ids)"),
                                          {"ids": former})).scalars()) if former else Counter()
        rooms.pop(series_id, None)
        if rooms:
            survivor = min(rooms, key=lambda r: (-rooms[r], str(r)))
            singleton = await db.scalar(text("SELECT kind = 'singleton' FROM series WHERE id = :s"), {"s": series_id})
            book = former[0] if singleton and len(former) == 1 else None
            stats.moved_threads += await retire_series(db, series_id, survivor, book)
            stats.retired_series += 1


async def load_release(db: AsyncSession, release: Release, *, force: bool = False) -> LoadStats:
    """Load ``release`` inside the caller's transaction. See the module docstring."""
    stats = LoadStats(release.version)
    if await db.get(CatalogRelease, release.version) is not None:
        stats.noop = True
        return stats
    loaded = (await db.execute(select(CatalogRelease.version))).scalars().all()
    latest = max(loaded, key=version_key, default=None)
    if latest and version_key(release.version) < version_key(latest) and not force:
        raise CatalogLoadError(f"{release.version} is older than loaded {latest}; pass --force to load it anyway")

    stats.rows = await _stage(db, release)
    stats.reslugged = await _reslug_collisions(db)
    adoptions = await _adoptions(db)
    former_rooms: dict[uuid.UUID, list[uuid.UUID]] = {}
    for runtime, target in adoptions.items():
        room = await db.scalar(text("SELECT series_id FROM works WHERE id = :w"), {"w": runtime})
        former_rooms.setdefault(room, []).append(target)
    old_rooms = dict((await db.execute(text(
        "SELECT w.id, w.series_id FROM works w WHERE w.catalog_release IS NOT NULL"))).all())

    db.add(CatalogRelease(version=release.version, manifest=release.manifest))
    await db.flush()
    for statement in _UPSERTS:
        await db.execute(text(statement), {"version": release.version})

    # A book that changed rooms takes the threads tagged to it; untagged ones stay.
    for work_id, old in old_rooms.items():
        new = await db.scalar(text("SELECT series_id FROM works WHERE id = :w"), {"w": work_id})
        if new != old:
            stats.moved_threads += (await db.execute(text(
                "UPDATE threads SET series_id = :new WHERE work_id = :w AND series_id = :old"),
                {"new": new, "old": old, "w": work_id})).rowcount or 0

    db.expire_all()  # the SQL above changed rows the session may hold
    for runtime, target in sorted(adoptions.items(), key=lambda kv: str(kv[0])):
        await _merge(db, runtime, target)
    stats.adopted = len(adoptions)
    retired, moved = await _retire_emptied_rooms(db, former_rooms)
    stats.retired_series += retired
    stats.moved_threads += moved
    await _settle_absent(db, release.version, stats, old_rooms)
    # Genres last: adoption merges have already carried runtime votes onto release works.
    rows = (await db.execute(text("SELECT id, genre_slugs FROM stage_works"))).all()
    await genres_service.set_inferences_bulk(db, {wid: slugs or [] for wid, slugs in rows}, "catalog")
    await db.flush()
    for table in ("works", "series", "books", "series_members", "work_aliases"):
        await db.execute(text(f"ANALYZE {table}"))
    return stats
