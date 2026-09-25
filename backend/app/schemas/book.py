from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.shelf import ShelfStatus
from app.models.work import Work, WorkKind

if TYPE_CHECKING:  # pragma: no cover
    # Type-only: importing this at runtime would make schemas depend on
    # services, inverting the layering (services -> schemas -> models).
    from app.services.works import WorkPresentation


class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    external_id: str
    title: str | None
    subtitle: str | None = None
    author: str | None
    cover_url: str | None
    description: str | None
    publisher: str | None = None
    published_date: date | None = None
    published_year: int | None
    isbn_13: str | None = None
    page_count: int | None = None
    average_rating: float | None = None
    ratings_count: int | None = None
    language: str | None = None
    categories: list[str] | None = None
    maturity_rating: str | None = None
    info_link: str | None = None
    preview_link: str | None = None
    genre_id: UUID | None
    shelf_status: ShelfStatus | None = None


class WorkOut(BaseModel):
    """A book as readers mean it. Cover and description come from the work's
    representative edition, resolved by the route — never by a lazy relationship
    load, which would raise MissingGreenlet mid-serialization."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    subtitle: str | None = None
    author: str
    first_publish_year: int | None = None
    kind: WorkKind
    genre_id: UUID | None = None
    cover_url: str | None = None
    description: str | None = None
    edition_count: int = 0
    shelf_status: ShelfStatus | None = None


def work_out(
    work: Work,
    presentation: "WorkPresentation | None" = None,
    shelf_status: ShelfStatus | None = None,
) -> WorkOut:
    """Build a WorkOut from scalar columns plus its presentation row."""
    return WorkOut(
        id=work.id,
        title=work.title,
        subtitle=work.subtitle,
        author=work.author,
        first_publish_year=work.first_publish_year,
        kind=work.kind,
        genre_id=work.genre_id,
        cover_url=presentation.cover_url if presentation else None,
        description=presentation.description if presentation else None,
        edition_count=presentation.edition_count if presentation else 0,
        shelf_status=shelf_status,
    )


class GenreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str | None


class ShelfIn(BaseModel):
    status: Literal["want_to_read", "reading", "read"]


class ShelfOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    work_id: UUID
    status: ShelfStatus
    created_at: datetime
