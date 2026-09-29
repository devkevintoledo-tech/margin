import pytest

from app.models import CorrectionOp, SeriesKind
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.keys import (
    MissingKey, edition_key, exported, release_series_key, series_key_of, work_key,
)
from app.services.librarian.record import clean_reason, latest_for_subject, live_work, record
from app.services.series_identity import new_series_key
from tests.librarian_factories import make_edition, make_series, make_user, make_work


async def test_keys_for_open_library_and_release_rows(db_session):
    saga = await make_series(db_session, "Red Rising", release="2026.10.1")
    book = await make_work(db_session, "Golden Son", series=saga, ol_id="OL31W")
    edition = await make_edition(db_session, book, ol_id="OL300M")
    assert (work_key(book), edition_key(edition)) == ("OL31W", "OL300M")
    assert series_key_of(saga) == release_series_key(saga) == "ol:red rising"


async def test_missing_keys_name_what_is_missing(db_session):
    runtime = await make_series(db_session, "Dune Saga")  # external_id franchise:dune saga
    heuristic = await make_work(db_session, "Obscure Book", series=runtime)
    google = await make_edition(db_session, heuristic)
    assert series_key_of(runtime) == "ol:dune saga"
    with pytest.raises(MissingKey, match="no Open Library id"):
        work_key(heuristic)
    with pytest.raises(MissingKey, match="Google Books volume"):
        edition_key(google)
    with pytest.raises(MissingKey, match="not in a catalog release"):
        release_series_key(runtime)
    single = await make_series(db_session, "Lonely", kind=SeriesKind.singleton)
    with pytest.raises(MissingKey, match="single book"):
        series_key_of(single)


def test_exported_turns_a_missing_key_into_a_reason():
    def build():
        raise MissingKey("nope")
    assert exported(lambda: [{"reject_series": "ol:x"}]) == ([{"reject_series": "ol:x"}], None)
    assert exported(build) == (None, "nope")


def test_new_series_key_is_normalized():
    assert new_series_key("The Lord of the Rings!") == "ol:the lord of the rings"


def test_blank_reason_is_refused():
    assert clean_reason("  typo in title \n") == "typo in title"
    for blank in ("", "   ", None):
        with pytest.raises(Invalid):
            clean_reason(blank)


async def test_live_work_refuses_a_tombstone(db_session):
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    a.merged_into_id = b.id
    with pytest.raises(Conflict):
        live_work(a)


async def test_latest_for_subject_orders_fixes_made_in_one_transaction(db_session):
    user = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Saga", release="2026.10.1")
    book = await make_work(db_session, "One", series=saga, ol_id="OL9W")
    common = dict(user=user, reason="r", payload={}, entries=[{"x": 1}], runtime_only_reason=None)
    first = await record(db_session, op=CorrectionOp.set_position, work=book, series=saga, **common)
    second = await record(db_session, op=CorrectionOp.set_position, work=book, series=saga, **common)
    rename = await record(db_session, op=CorrectionOp.rename_series, series=saga, **common)
    assert (await latest_for_subject(db_session, first)).id == second.id
    assert (await latest_for_subject(db_session, rename)).id == rename.id
