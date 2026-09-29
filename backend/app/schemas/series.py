from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.series import SeriesKind, SeriesProvenance
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
    # Place in the series, from the catalog: 2.0, or 2.5 for a novella. Null
    # when unknown — the page falls back to publication order.
    position: float | None = None
    # The child series this book sits in (Mistborn inside the Cosmere), or
    # null when it belongs to the room directly.
    subseries: str | None = None
    # Librarian edit mode only: marks rows a correction placed ('override').
    provenance: SeriesProvenance | None = None


class SeriesOut(BaseModel):
    id: UUID
    slug: str
    name: str
    kind: SeriesKind
    dissolved: bool = False
    # One description for the page: the singleton's own book, otherwise the
    # first member's. Per-book blurbs are deliberately absent.
    description: str | None = None
    works: list[SeriesWorkOut] = []


class SeriesThreadCreate(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "title": "Who is the real villain?",
                    "work_id": "3a1f0e2d-4c5b-4a69-8d7e-6f5a4b3c2d10",
                    "content": "Tagged to one book; omit work_id to talk about the whole series.",
                }
            ]
        },
    )

    title: str = Field(min_length=1)
    work_id: UUID | None = None
    body: str | None = Field(default=None, alias="content")
