from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
# Through the package, per CLAUDE.md: app.models.__init__ imports every model,
# so Base.metadata is complete without importing Base directly for its side
# effect.
from app.models import Book, Genre, Shelf, Work
from app.schemas.book import ShelfIn, ShelfOut, WorkOut, work_out
from app.services import search
from app.services.auth import get_current_user, get_current_user_optional
from app.services.works import canonical_work, load_work_presentation

router = APIRouter(prefix="/works", tags=["works"])

# Fields copied verbatim from the normalized Google Books dict onto an edition.
_EDITION_FIELDS = (
    "title", "subtitle", "author", "cover_url", "description", "publisher",
    "published_date", "published_year", "isbn_13", "page_count",
    "average_rating", "ratings_count", "language", "categories",
    "maturity_rating", "info_link", "preview_link",
)


async def _get_work_or_404(work_id: UUID, db: AsyncSession) -> Work:
    work = await db.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return await canonical_work(db, work)


async def _upsert_editions(
    db: AsyncSession, results: list[dict]
) -> tuple[list[Book], dict[UUID, UUID]]:
    """Upsert every volume as an edition; return them in relevance order.

    The second return value maps ``Book.id`` to the genre its categories imply.
    Genre belongs to the work, so the hint is passed through rather than stored
    on the edition.
    """
    slugs = {r["genre_slug"] for r in results if r.get("genre_slug")}
    genre_ids: dict[str, UUID] = {}
    if slugs:
        rows = (await db.execute(select(Genre.slug, Genre.id).where(Genre.slug.in_(slugs)))).all()
        genre_ids = {slug: gid for slug, gid in rows}

    editions: list[Book] = []
    hints: dict[UUID, UUID] = {}
    for item in results:
        ext_id = item.get("external_id")
        if not ext_id:
            continue

        stmt = select(Book).where(Book.source == "google_books", Book.external_id == ext_id)
        existing = (await db.execute(stmt)).scalars().first()

        if existing:
            for field in _EDITION_FIELDS:
                value = item.get(field)
                if value:  # only overwrite when Google gave us something
                    setattr(existing, field, value)
            edition = existing
        else:
            edition = Book(
                source="google_books",
                external_id=ext_id,
                **{f: item.get(f) for f in _EDITION_FIELDS},
            )
            db.add(edition)

        await db.flush()  # get generated id
        editions.append(edition)
        if item.get("genre_slug") in genre_ids:
            hints[edition.id] = genre_ids[item["genre_slug"]]

    return editions, hints


async def _to_work_outs(
    db: AsyncSession, works: list[Work], shelf_by_work: dict[UUID, str] | None = None
) -> list[WorkOut]:
    presentation = await load_work_presentation(db, [w.id for w in works])
    shelf_by_work = shelf_by_work or {}
    return [
        work_out(w, presentation.get(w.id), shelf_by_work.get(w.id)) for w in works
    ]


@router.get("/search", response_model=list[WorkOut])
async def search_works(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """Answer from the local catalog, filling it from Open Library when cold.

    No upstream call happens on a query the database has already resolved, so
    the common case never leaves the process.
    """
    works = await search.search(db, q)
    return await _to_work_outs(db, works)


@router.get("/{work_id}", response_model=WorkOut)
async def get_work(
    work_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    """Catalog lookup by id. The frontend only uses it to redirect a legacy /works/:id URL to its series."""
    work = await _get_work_or_404(work_id, db)
    shelf_by_work: dict[UUID, str] = {}
    if current_user is not None:
        stmt = select(Shelf.status).where(
            Shelf.user_id == current_user.id, Shelf.work_id == work.id
        )
        found = (await db.execute(stmt)).scalar_one_or_none()
        if found is not None:
            shelf_by_work[work.id] = found
    return (await _to_work_outs(db, [work], shelf_by_work))[0]


@router.post("/{work_id}/shelf", response_model=ShelfOut, status_code=status.HTTP_201_CREATED)
async def add_to_shelf(
    work_id: UUID,
    payload: ShelfIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    work = await _get_work_or_404(work_id, db)

    stmt = select(Shelf).where(Shelf.user_id == current_user.id, Shelf.work_id == work.id)
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Book already on shelf. Use PUT to update.",
        )

    shelf = Shelf(user_id=current_user.id, work_id=work.id, status=payload.status)
    db.add(shelf)
    await db.flush()
    return shelf


@router.put("/{work_id}/shelf", response_model=ShelfOut)
async def update_shelf(
    work_id: UUID,
    payload: ShelfIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    work = await _get_work_or_404(work_id, db)
    stmt = select(Shelf).where(Shelf.user_id == current_user.id, Shelf.work_id == work.id)
    shelf = (await db.execute(stmt)).scalars().first()
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf entry not found")

    shelf.status = payload.status
    await db.flush()
    return shelf


@router.delete("/{work_id}/shelf", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_shelf(
    work_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    work = await _get_work_or_404(work_id, db)
    stmt = select(Shelf).where(Shelf.user_id == current_user.id, Shelf.work_id == work.id)
    shelf = (await db.execute(stmt)).scalars().first()
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf entry not found")

    await db.delete(shelf)
