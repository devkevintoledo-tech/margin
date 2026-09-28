import re
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import Series, Work
from app.services.catalog_loader import load_release, read_release
from app.services.librarian.export import exportable, render, runtime_only
from app.services.librarian.identity import merge, split
from app.services.librarian.placement import rename_series, set_series
from app.services.librarian.undo import revert
from app.services.series_identity import release_series_id
from scripts.export_overrides import run
from tests.librarian_factories import make_member, make_series, make_user, make_work

R = "2026.10.1"
REPO = Path(__file__).resolve().parents[2]


async def some_fixes(db):
    lib = await make_user(db, librarian=True, username="ada")
    saga = await make_series(db, "Song of Ice", release=R, key="wd:Q45875")
    await rename_series(db, lib, saga, "A Song of Ice and Fire", reason="full title\nper the cover")
    book = await make_work(db, "A Game of Thrones", ol_id="OL10W")
    await set_series(db, lib, book, series=saga, position=1, reason="book one")
    await set_series(db, lib, await make_work(db, "Heuristic"), new_series_name="Nowhere", reason="runtime")
    undone = await set_series(db, lib, await make_work(db, "Undone", ol_id="OL11W"), series=saga, reason="oops")
    await revert(db, lib, undone)
    return lib


async def test_render_is_deterministic_ordered_and_commented(db_session):
    await some_fixes(db_session)
    rows = await exportable(db_session)
    text = render(rows)
    assert text == render(await exportable(db_session))
    assert [c.reason for c, _ in rows] == ["full title\nper the cover", "book one"]  # no runtime-only, no reverted
    assert re.search(r"^# full title  \(ada, \d{4}-\d{2}-\d{2}, correction [0-9a-f]{8}\)$", text, re.M)
    assert "\n# per the cover\n" in text
    assert text.index("rename_series") < text.index("set_series")
    assert [c.reason for c, _ in await runtime_only(db_session)] == ["runtime"]


async def test_run_writes_and_checks(db_session, tmp_path, capsys):
    await some_fixes(db_session)
    out = tmp_path / "z-librarian.yaml"
    assert await run(db_session, out, check=True) == 1  # missing
    assert await run(db_session, out, check=False) == 0
    assert await run(db_session, out, check=True) == 0
    assert "runtime-only" in capsys.readouterr().out
    out.write_text(out.read_text() + "# edited\n")
    assert await run(db_session, out, check=True) == 1


def _load_overrides():
    if not (REPO / "pipeline" / "overrides.py").exists():
        pytest.skip("pipeline/ is not present next to backend/ (mount it; see the plan's PYTEST)")
    sys.path.insert(0, str(REPO))
    try:
        from pipeline import overrides
    finally:
        sys.path.remove(str(REPO))
    return overrides


async def test_the_pipeline_reads_the_export(db_session, tmp_path):
    overrides = _load_overrides()
    await some_fixes(db_session)
    saga = (await db_session.execute(select(Series).where(Series.external_id == "wd:Q45875"))).scalar_one()
    merged_into = await make_work(db_session, "Target", ol_id="OL1W")
    lib = await make_user(db_session, librarian=True)
    await merge(db_session, lib, await make_work(db_session, "Loser", ol_id="OL2W"), merged_into,
                reason="dup", confirm=True)
    (tmp_path / "z-librarian.yaml").write_text(render(await exportable(db_session)))

    parsed = overrides.load_overrides(tmp_path)

    assert [type(o).__name__ for o in parsed] == ["RenameSeries", "SetSeries", "MergeWorks"]
    assert (parsed[0].series, parsed[0].name) == ("wd:Q45875", "A Song of Ice and Fire")
    assert (parsed[1].work, parsed[1].series, parsed[1].position) == ("OL10W", "wd:Q45875", 1.0)
    assert (parsed[2].survivor, parsed[2].losers) == ("OL1W", ("OL2W",))
    assert saga.name == "A Song of Ice and Fire"


async def test_a_release_that_applied_the_fixes_adopts_the_runtime_rows(db_session, write_release):
    """Export a merge, a split and a move; load a release built from them: the
    runtime rows are adopted, not duplicated."""
    A = uuid.uuid4()
    W10, W11, E1, E2, E3 = (uuid.uuid4() for _ in range(5))
    series = [{"id": A, "name": "Alpha", "slug": "alpha", "key": "ol:alpha"}]
    works = [{"id": W10, "ol_work_id": "OL10W", "title": "Ten", "series_id": A},
             {"id": W11, "ol_work_id": "OL11W", "title": "Eleven", "series_id": A}]
    editions = [{"id": e, "ol_edition_id": f"OL{i}M", "work_id": W10, "title": t}
                for i, (e, t) in enumerate([(E1, "Ten"), (E2, "Ten"), (E3, "Ten Prequel")], start=1)]
    members = [{"series_id": A, "work_id": W10, "position": 1.0}, {"series_id": A, "work_id": W11, "position": 2.0}]
    await load_release(db_session, read_release(write_release(
        R, series=series, works=works, editions=editions, series_members=members)))

    lib = await make_user(db_session, librarian=True)
    ten, eleven = await db_session.get(Work, W10), await db_session.get(Work, W11)
    await merge(db_session, lib, eleven, ten, reason="dup", confirm=True)
    cut = await split(db_session, lib, ten, [E3], reason="prequel", confirm=True)
    runtime_split = uuid.UUID(cut.payload["new_work"])
    await set_series(db_session, lib, ten, new_series_name="Beta", reason="own saga")

    BETA, S = release_series_id("ol:beta"), uuid.uuid4()
    v2 = read_release(write_release(
        "2026.11.1",
        series=[*series, {"id": BETA, "name": "Beta", "slug": "beta", "key": "ol:beta"}],
        works=[{"id": W10, "ol_work_id": "OL10W", "title": "Ten", "series_id": BETA},
               {"id": S, "ol_work_id": "OL10W~OL3M", "title": "Ten Prequel", "series_id": A}],
        editions=[{**editions[0]}, {**editions[1]}, {**editions[2], "work_id": S}],
        series_members=[{"series_id": BETA, "work_id": W10, "position": None},
                        {"series_id": A, "work_id": S, "position": None}],
        work_aliases=[{"ol_work_id": "OL11W", "work_id": W10}],
    ))
    await load_release(db_session, v2)

    assert await db_session.scalar(select(func.count()).select_from(Series)
                                   .where(Series.canonical_key == "beta")) == 1
    assert await db_session.scalar(select(Work.series_id).where(Work.id == W10)) == BETA
    live_splits = (await db_session.execute(select(Work.id).where(
        Work.title == "Ten Prequel", Work.merged_into_id.is_(None)))).scalars().all()
    assert live_splits == [S]
    assert await db_session.scalar(select(Work.merged_into_id).where(Work.id == runtime_split)) == S
    assert await db_session.scalar(select(Work.merged_into_id).where(Work.id == W11)) == W10
