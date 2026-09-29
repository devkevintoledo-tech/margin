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
