from sqlalchemy import select, text

from app.models import CorrectionOp, Genre, GenreInference, WorkGenre, effective_work_genres
from tests.librarian_factories import make_work


async def test_the_view_exists_under_create_all_and_reads_empty(db_session):
    rows = (await db_session.execute(select(effective_work_genres))).all()
    assert rows == []


async def test_genre_hierarchy_columns(db_session):
    parent = Genre(name="Fantasy", slug="fantasy")
    db_session.add(parent)
    await db_session.flush()
    child = Genre(name="Grimdark", slug="grimdark", parent_id=parent.id, position=1)
    db_session.add(child)
    await db_session.flush()
    assert (child.parent_id, child.position, child.retired_at) == (parent.id, 1, None)


async def test_inference_source_is_checked(db_session):
    import pytest
    from sqlalchemy.exc import IntegrityError

    g = Genre(name="Fantasy", slug="fantasy")
    db_session.add(g)
    w = await make_work(db_session, "The Hobbit")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(GenreInference(work_id=w.id, genre_id=g.id, source="guess"))
            await db_session.flush()


async def test_author_doc_is_generated(db_session):
    w = await make_work(db_session, "Red Rising", author="Pierce Brown")
    hit = await db_session.scalar(text(
        "SELECT count(*) FROM works WHERE id = :id AND author_doc @@ plainto_tsquery('simple', 'brown')"),
        {"id": w.id})
    assert hit == 1


def test_veto_genre_is_a_correction_op():
    assert CorrectionOp.veto_genre.value == "veto_genre"
