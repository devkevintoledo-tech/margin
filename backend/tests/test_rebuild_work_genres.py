from app.services import genres as genres_service
from scripts.rebuild_work_genres import rebuild_chunk
from tests.genre_factories import effective
from tests.librarian_factories import make_work


async def test_reinfer_recomputes_inferences_from_stored_subjects(db_session, taxonomy):
    w = await make_work(db_session, "Dune")
    w.subjects = "genre:science fiction\nSpace opera"
    await genres_service.set_inferences(db_session, w, {"mystery"}, "open_library")
    await rebuild_chunk(db_session, [w.id], reinfer=True)
    assert set(await effective(db_session, w)) == {"science-fiction"}


async def test_reinfer_leaves_a_work_without_stored_subjects_alone(db_session, taxonomy):
    # A work ingested before subjects were stored keeps the genre the
    # works.genre_id migration gave it: no subjects is no evidence, not "no genre".
    w = await make_work(db_session, "Dune")
    w.subjects = None
    await genres_service.set_inferences(db_session, w, {"science-fiction"}, "open_library")
    await rebuild_chunk(db_session, [w.id], reinfer=True)
    assert set(await effective(db_session, w)) == {"science-fiction"}
