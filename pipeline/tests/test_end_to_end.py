"""The whole pipeline over the fixture world, twice: byte-identical releases."""

import json

import pyarrow.parquet as pq
import pytest
import respx

from pipeline import runner
from pipeline.golden import GoldenGateError
from pipeline.stages import publish
from pipeline.stages.publish import PublishError, previous_release
from pipeline.tests.conftest import make_ctx
from pipeline.tests.fixtures import world

PARQUET = ["editions", "series", "series_members", "work_aliases", "works"]


def build(tmp_path, name, version="2026.10.1", releases=None):
    base = tmp_path / name
    base.mkdir()
    with respx.mock(assert_all_called=False) as router:
        world.serve(router)
        ctx = make_ctx(base, version=version, releases=releases)
        runner.run(ctx)
    return ctx, ctx.releases_dir / f"catalog-{version}"


def test_two_runs_produce_byte_identical_parquet(tmp_path):
    _, first = build(tmp_path, "a")
    _, second = build(tmp_path, "b")
    for name in PARQUET:
        assert (first / f"{name}.parquet").read_bytes() == (second / f"{name}.parquet").read_bytes(), name


def test_the_release_folder_holds_the_contract(tmp_path):
    _, release = build(tmp_path, "a")
    assert sorted(p.name for p in release.iterdir()) == sorted(
        [f"{n}.parquet" for n in PARQUET] + ["manifest.json", "report.md"])
    manifest = json.loads((release / "manifest.json").read_text())
    assert manifest["version"] == "2026.10.1" and manifest["schema_version"] == 1
    assert {s["name"] for s in manifest["sources"]} == {"ratings", "reading_log", "works", "authors", "editions", "wikidata"}
    assert set(manifest["files"]) == {f"{n}.parquet" for n in PARQUET} | {"report.md"}
    series = {s["key"]: s for s in pq.read_table(release / "series.parquet").to_pylist()}
    assert series["wd:Q45875"]["slug"] == "a-song-of-ice-and-fire"
    assert series["single:OL63W"]["kind"] == "singleton"
    works = {w["ol_work_id"]: w for w in pq.read_table(release / "works.parquet").to_pylist()}
    assert works["OL30W"]["series_id"] == series["ol:red rising"]["id"]
    assert "OL36W" not in works
    report = (release / "report.md").read_text()
    for heading in ("## Golden set", "## Select drops", "## Imprint rejections", "## Suspicious series"):
        assert heading in report


def test_a_release_is_never_overwritten(tmp_path):
    ctx, _ = build(tmp_path, "a")
    with pytest.raises(PublishError, match="immutable"):
        publish.run(ctx)


def test_a_golden_regression_blocks_the_release(tmp_path):
    base = tmp_path / "a"
    base.mkdir()
    with respx.mock(assert_all_called=False) as router:
        world.serve(router)
        ctx = make_ctx(base)
        ctx.golden_path.write_text("- name: Red Rising\n  members: [OL31W, OL30W]\n")
        with pytest.raises(GoldenGateError):
            runner.run(ctx)
    assert not ctx.releases_dir.exists() or not any(ctx.releases_dir.iterdir())


def test_a_second_release_reports_its_diff(tmp_path):
    releases = tmp_path / "releases"
    build(tmp_path, "a", "2026.10.1", releases)
    _, second = build(tmp_path, "b", "2026.11.1", releases)
    assert previous_release(releases, "2026.11.1").name == "catalog-2026.10.1"
    assert "Compared with `catalog-2026.10.1`." in (second / "report.md").read_text()


def test_upload_attaches_a_tarball_to_a_tagged_release(tmp_path):
    _, release = build(tmp_path, "a")
    calls = []
    publish.upload(release, "2026.10.1", run=lambda args, check: calls.append(args))
    assert calls[0][:4] == ["gh", "release", "create", "catalog-2026.10.1"]
    assert (release.parent / "catalog-2026.10.1.tar.gz").exists()
