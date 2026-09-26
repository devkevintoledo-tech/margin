from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.series import SeriesKind
from app.models.shelf import ShelfStatus


class SeriesRef(BaseModel):
    """Enough of a series to link to it and label a card."""

    slug: str
    name: str
    kind: SeriesKind


class SeriesWorkOut(BaseModel):
    """One book row on a series page: identity, art, and the shelf control's state."""

    id: UUID
    title: str
    author: str
    first_publish_year: int | None = None
    cover_url: str | None = None
    shelf_status: ShelfStatus | None = None


class SeriesOut(BaseModel):
    slug: str
    name: str
    kind: SeriesKind
    # One description for the page: the singleton's own book, otherwise the
    # first member's. Per-book blurbs are deliberately absent.
    description: str | None = None
    works: list[SeriesWorkOut] = []


class SeriesThreadCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1)
    work_id: UUID | None = None
    body: str | None = Field(default=None, alias="content")
