from app.models import Series
from app.services.librarian.placement import remove_from_series, set_series
from app.services.librarian.undo import revert
from app.services.series import assign_series
from tests.librarian_factories import make_series, make_user, make_work


async def test_a_librarian_placed_book_is_not_re_roomed_by_search(db_session):
    lib = await make_user(db_session, librarian=True)
    x = await make_work(db_session, "Iron Gold", ol_id="OL40W")
    x.subjects = "franchise:Red Rising"
    await db_session.flush()
    c = await set_series(db_session, lib, x, new_series_name="Red Rising Saga Two", reason="r")

    room = await assign_series(db_session, x)  # what a search re-ingest does
    assert room.id == c.series_id and x.series_id == c.series_id

    await revert(db_session, lib, c)
    room = await assign_series(db_session, x)  # no longer protected: the tag wins again
    assert room.name == "Red Rising"


async def test_a_removed_book_stays_on_its_own_page(db_session):
    lib = await make_user(db_session, librarian=True)
    first = await make_work(db_session, "Red Rising", ol_id="OL30W")
    x = await make_work(db_session, "Not Red Rising", ol_id="OL41W")
    for w in (first, x):
        w.subjects = "franchise:Red Rising"
    await db_session.flush()
    saga = await assign_series(db_session, first)
    assert (await assign_series(db_session, x)).id == saga.id

    await remove_from_series(db_session, lib, saga, x, reason="mis-tagged")
    own = x.series_id
    assert own != saga.id
    assert (await assign_series(db_session, x)).id == own
