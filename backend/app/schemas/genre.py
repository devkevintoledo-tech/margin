from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class GenreRef(BaseModel):
    slug: str
    name: str


class WorkGenreOut(BaseModel):
    slug: str
    name: str
    parent_slug: str | None = None
    score: int  # distinct readers, subgenres rolled up; 0 for an inferred genre
    direct_votes: int
    my_vote: bool | None = None  # null for anonymous callers
    vetoed: bool = False  # librarians only
    veto_id: UUID | None = None  # the correction to undo; librarians only


class WorkGenresOut(BaseModel):
    source: Literal["readers", "inferred", "none"]
    genres: list[WorkGenreOut]
    my_vote_count: int | None = None


class GenreChild(GenreRef):
    book_count: int = 0


class GenreNode(BaseModel):
    """A top-level genre on the home page, with its subgenres."""

    id: UUID
    slug: str
    name: str
    description: str | None = None
    children: list[GenreRef] = []


class GenreOut(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    parent: GenreRef | None = None
    children: list[GenreChild] = []
    retired: bool = False
    room_slug: str  # where this genre's discussion lives: itself, or its parent
