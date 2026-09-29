"""Row builders for genre tests. Votes and vetoes are inserted directly here so
the effective-genre rule can be tested before the services that write them."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import CatalogCorrection, CorrectionOp, Genre, GenreVote, WorkGenre, effective_work_genres


async def make_genre(db, slug, parent=None, retired=False, position=0):
    g = Genre(name=slug.replace("-", " ").title(), slug=slug, parent_id=parent.id if parent else None,
              position=position, retired_at=datetime.now(timezone.utc) if retired else None)
    db.add(g)
    await db.flush()
    return g


async def add_vote(db, user, work, genre):
    v = GenreVote(user_id=user.id, work_id=work.id, genre_id=genre.id)
    db.add(v)
    await db.flush()
    return v


async def add_veto(db, librarian, work, genre, reverted=False):
    c = CatalogCorrection(
        op=CorrectionOp.veto_genre, user_id=librarian.id, reason="wrong genre",
        payload={"work_id": str(work.id), "genre_id": str(genre.id)}, override=None,
        runtime_only_reason="the pipeline has no genre overrides", work_id=work.id,
        reverted_at=datetime.now(timezone.utc) if reverted else None,
    )
    db.add(c)
    await db.flush()
    return c


async def effective(db, work):
    """``{slug: (score, source)}`` straight from the view."""
    rows = (await db.execute(
        select(Genre.slug, effective_work_genres.c.score, effective_work_genres.c.source)
        .join(Genre, Genre.id == effective_work_genres.c.genre_id)
        .where(effective_work_genres.c.work_id == work.id))).all()
    return {slug: (score, source) for slug, score, source in rows}


async def summary(db):
    rows = (await db.execute(select(WorkGenre))).scalars().all()
    return {(r.work_id, r.genre_id, r.direct_votes, r.score, r.inferred, r.vetoed) for r in rows}
