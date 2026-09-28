import types

import duckdb
import pytest

from pipeline import runner
from pipeline.config import BuildContext
from pipeline.db import swap_in, table_names


@pytest.fixture
def ctx(tmp_path):
    return BuildContext(build_dir=tmp_path, con=duckdb.connect())


def _fake_stages(monkeypatch, calls, fail=None):
    def load(name):
        def run(ctx):
            calls.append(name)
            if name == fail:
                raise RuntimeError(f"{name} failed")
        return types.SimpleNamespace(run=run)
    monkeypatch.setattr(runner, "load_stage", load)


def test_runs_every_stage_in_order(ctx, monkeypatch):
    calls = []
    _fake_stages(monkeypatch, calls)
    runner.run(ctx)
    assert calls == ["fetch", "select", "extract", "group", "publish"]


def test_resumes_from_a_stage(ctx, monkeypatch):
    calls = []
    _fake_stages(monkeypatch, calls)
    runner.run(ctx, start="group")
    assert calls == ["group", "publish"]


def test_rejects_a_backwards_range():
    with pytest.raises(ValueError):
        runner.stage_range("group", "select")


def test_a_failed_stage_leaves_the_previous_tables(ctx):
    ctx.con.execute("CREATE TABLE works AS SELECT 1 AS v")
    ctx.con.execute("CREATE TABLE tmp_works AS SELECT 2 AS v")
    ctx.con.execute("CREATE TABLE tmp_editions AS SELECT 3 AS v")
    # tmp_series does not exist, so the swap fails part-way and must roll back.
    with pytest.raises(Exception):
        swap_in(ctx.con, ["works", "series"])
    assert ctx.con.execute("SELECT v FROM works").fetchone() == (1,)


def test_a_new_run_drops_a_crashed_stages_temp_tables(ctx, monkeypatch):
    ctx.con.execute("CREATE TABLE tmp_half_written AS SELECT 1 AS v")
    _fake_stages(monkeypatch, [])
    runner.run(ctx, start="publish")
    assert "tmp_half_written" not in table_names(ctx.con)


def test_swap_replaces_tables(ctx):
    ctx.con.execute("CREATE TABLE works AS SELECT 1 AS v")
    ctx.con.execute("CREATE TABLE tmp_works AS SELECT 2 AS v")
    swap_in(ctx.con, ["works"])
    assert ctx.con.execute("SELECT v FROM works").fetchone() == (2,)
    assert "tmp_works" not in table_names(ctx.con)
