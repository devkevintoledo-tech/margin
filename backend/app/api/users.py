from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.shelf import Shelf, ShelfStatus
from app.models.user import User
from app.models.work import Work
from app.schemas.book import WorkOut, work_out
from app.schemas.user import UserOut
from app.services.works import load_work_presentation

router = APIRouter(prefix="/users", tags=["users"])


class UserWithShelves(UserOut):
    shelves: dict[str, list[WorkOut]] = {s.value: [] for s in ShelfStatus}


@router.get("/{username}", response_model=UserWithShelves)
async def get_user_profile(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> UserWithShelves:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Shelf entries render as book cards, so each one is the shelved work
    # itself (with its status), newest first.
    rows = (
        await db.execute(
            select(Work, Shelf.status)
            .join(Shelf, Shelf.work_id == Work.id)
            .where(Shelf.user_id == user.id)
            .order_by(Shelf.created_at.desc())
        )
    ).all()
    presentation = await load_work_presentation(db, [w.id for w, _ in rows])

    grouped: dict[str, list[WorkOut]] = {s.value: [] for s in ShelfStatus}
    for w, shelf_status in rows:
        grouped[shelf_status.value].append(
            work_out(w, presentation.get(w.id), shelf_status)
        )

    # Build explicitly from scalar columns: model_validate(user) would read
    # the lazy `shelves` relationship and raise MissingGreenlet.
    return UserWithShelves(
        id=user.id,
        email=user.email,
        username=user.username,
        avatar_url=user.avatar_url,
        created_at=user.created_at,
        shelves=grouped,
    )
