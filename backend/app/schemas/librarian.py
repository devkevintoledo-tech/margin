from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import CorrectionOp


class _Reasoned(BaseModel):
    # Non-empty after strip is enforced by the service (clean_reason), so the
    # message is the same whichever route refuses it.
    reason: str


class MergeIn(_Reasoned):
    into_work_id: UUID
    confirm: bool = False


class SplitIn(_Reasoned):
    edition_ids: list[UUID]
    confirm: bool = False


class MoveIn(_Reasoned):
    series_id: UUID | None = None
    new_series_name: str | None = Field(default=None, max_length=500)  # series.name is String(500)
    position: float | None = Field(default=None, allow_inf_nan=False)


class PositionIn(_Reasoned):
    work_id: UUID
    position: float | None = Field(default=None, allow_inf_nan=False)


class RemoveIn(_Reasoned):
    work_id: UUID


class RenameIn(_Reasoned):
    name: str = Field(max_length=500)


class DissolveIn(_Reasoned):
    pass


class CorrectionOut(BaseModel):
    id: UUID
    op: CorrectionOp
    reason: str
    created_at: datetime
    user: str
    exportable: bool
    runtime_only_reason: str | None = None
    undoable: bool
    reverted_at: datetime | None = None
    room_slug: str | None = None  # where the subject lives now, so the page can follow it
    subject: str | None = None  # the subject work's title, or the series' name


class SeriesHit(BaseModel):
    id: UUID
    slug: str
    name: str
    book_count: int


class EditionOut(BaseModel):
    id: UUID
    title: str
    publisher: str | None = None
    published_year: int | None = None
    language: str | None = None
    source: str


class MergeSide(BaseModel):
    """One book in a merge preview, shown the way its own page shows it."""

    id: UUID
    title: str
    author: str
    first_publish_year: int | None = None
    # load_work_presentation's ladder, never a raw column: the representative
    # edition's cover, then OL's curated image; its blurb, then the work's.
    cover_url: str | None = None
    description: str | None = None
    # OL's total, then local rows: the number a search card shows for this book.
    edition_count: int = 0
    # Threads about this book: tagged with it, plus a singleton room's untagged ones.
    thread_count: int = 0
    shelf_count: int = 0
    series_slug: str | None = None  # the book's page
    series_name: str | None = None  # null for a singleton, which has no series chrome


class MergePreviewOut(BaseModel):
    source: MergeSide  # merges away
    target: MergeSide  # survives
    # What the merge moves: the numbers its 422 confirmation states.
    threads: int
    shelves: int
    editions: int
