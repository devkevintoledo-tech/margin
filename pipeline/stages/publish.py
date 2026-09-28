"""publish (spec §4.5): gate on the golden set, write an immutable release folder."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Callable

import pyarrow.parquet as pq

from pipeline import report
from pipeline.config import REPO, SCHEMA_VERSION, BuildContext
from pipeline.golden import MemberRow, evaluate, gate, load_golden
from pipeline.release import build_release

VERSION = re.compile(r"^(\d{4})\.(\d{2})\.(\d+)$")


class PublishError(RuntimeError):
    pass


def version_key(version: str) -> tuple[int, int, int]:
    match = VERSION.match(version)
    if not match:
        raise PublishError(f"release version must be YYYY.MM.N, got {version!r}")
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def previous_release(releases_dir: Path, version: str) -> Path | None:
    older = []
    for path in releases_dir.glob("catalog-*"):
        candidate = path.name.removeprefix("catalog-")
        if path.is_dir() and VERSION.match(candidate) and version_key(candidate) < version_key(version):
            older.append((version_key(candidate), path))
    return max(older)[1] if older else None


def git_commit() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}-dirty" if dirty else head


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def golden_result(ctx: BuildContext):
    con = ctx.con
    members: dict[str, list[MemberRow]] = defaultdict(list)
    for key, work, position, year, title in con.execute("""
            SELECT m.series_key, m.work_ol_id, m.position, w.first_publish_year, w.title
            FROM g_members m JOIN g_works w ON w.ol_id = m.work_ol_id""").fetchall():
        members[key].append(MemberRow(work, position, year, title))
    aliases = dict(con.execute("SELECT ol_id, work_ol_id FROM g_aliases").fetchall())
    return evaluate(load_golden(ctx.golden_path), members, resolve=lambda w: aliases.get(w, w))


def upload(release: Path, version: str, run: Callable = subprocess.run) -> None:
    """Attach ``catalog-<version>.tar.gz`` to a GitHub Release tagged ``catalog-<version>``."""
    tag = f"catalog-{version}"
    tarball = release.parent / f"{tag}.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(release, arcname=tag)
    manifest = json.loads((release / "manifest.json").read_text())
    notes = release.parent / f"{tag}.notes.md"
    notes.write_text("\n".join(
        [f"Catalog release {version} (schema {manifest['schema_version']}, pipeline {manifest['pipeline_commit']}).", ""]
        + [f"- {name}: {n:,} rows" for name, n in sorted(manifest["row_counts"].items())]
        + ["", "Sources:"] + [f"- {s['name']}: {s['url']} ({s['retrieved']})" for s in manifest["sources"]]) + "\n")
    run(["gh", "release", "create", tag, str(tarball), "--title", tag, "--notes-file", str(notes)], check=True)


def run(ctx: BuildContext) -> None:
    if not ctx.version:
        raise PublishError("publish needs a release version")
    version_key(ctx.version)
    final = ctx.releases_dir / f"catalog-{ctx.version}"
    if final.exists():
        raise PublishError(f"{final} already exists; a release folder is immutable, publish a new version")

    result = golden_result(ctx)
    gate(result)  # before anything is written

    tables = build_release(ctx.con)
    partial = ctx.releases_dir / f".catalog-{ctx.version}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    for name, table in tables.items():
        pq.write_table(table, partial / f"{name}.parquet", compression="zstd")
    slugs = dict(zip(tables["series"].column("key").to_pylist(), tables["series"].column("slug").to_pylist()))
    (partial / "report.md").write_text(
        report.render(ctx.con, ctx.version, result, slugs, previous_release(ctx.releases_dir, ctx.version)),
        encoding="utf-8")

    cursor = ctx.con.execute("SELECT * FROM sources ORDER BY name")
    columns = [d[0] for d in cursor.description]
    manifest = {
        "version": ctx.version,
        "schema_version": SCHEMA_VERSION,
        "pipeline_commit": git_commit(),
        "sources": [dict(zip(columns, r)) for r in cursor.fetchall()],
        "row_counts": {name: table.num_rows for name, table in sorted(tables.items())},
        "files": {p.name: _sha256(p) for p in sorted(partial.iterdir())},
    }
    (partial / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    partial.rename(final)
    if ctx.upload:
        upload(final, ctx.version)
