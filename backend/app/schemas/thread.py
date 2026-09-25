from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ThreadCreate(BaseModel):
    # Accept the frontend's payload as-is: genre threads are created by `slug`
    # and the opening post body arrives as `content`.
    model_config = ConfigDict(populate_by_name=True)

    title: str
    work_id: UUID | None = None
    genre_id: UUID | None = None
    genre_slug: str | None = None
    body: str | None = Field(default=None, alias="content")

    @model_validator(mode="after")
    def exactly_one_target(self) -> "ThreadCreate":
        has_work = self.work_id is not None
        has_genre = self.genre_id is not None or self.genre_slug is not None
        if has_work == has_genre:  # both set or neither set
            raise ValueError(
                "Exactly one of work_id or genre (genre_slug/genre_id) must be provided."
            )
        return self


class VoteIn(BaseModel):
    """A vote to set: 1 up, -1 down, 0 clears it."""

    value: int = Field(ge=-1, le=1)


class ThreadWorkRef(BaseModel):
    """Just enough of a work to render a link and a path segment."""

    model_config = {"from_attributes": True}

    id: UUID
    title: str


class ThreadGenreRef(BaseModel):
    """Just enough of a genre to render a link and a path segment."""

    model_config = {"from_attributes": True}

    id: UUID
    name: str
    slug: str


class ThreadOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    title: str
    user_id: UUID
    work_id: UUID | None
    genre_id: UUID | None
    score: int
    my_vote: int = 0
    created_at: datetime
    # The author's username, resolved by the route. Deliberately NOT named after
    # the `Thread.user` relationship, and defaulted, so `model_validate` on an
    # ORM object never triggers a lazy load (MissingGreenlet).
    author: str | None = None


class ThreadSummary(BaseModel):
    """List-view shape consumed by the frontend ThreadCard."""

    model_config = {"from_attributes": True}

    id: UUID
    title: str
    score: int
    my_vote: int = 0
    post_count: int
    author: str
    # The listing renders an age column; without this it had no date to format.
    created_at: datetime
    genre_slug: str | None = None
    work_id: UUID | None = None


class PostCreate(BaseModel):
    thread_id: UUID
    content: str
    parent_id: UUID | None = None


class PostOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    thread_id: UUID
    user_id: UUID
    parent_id: UUID | None
    content: str
    score: int
    my_vote: int = 0
    created_at: datetime
    updated_at: datetime
    # See ThreadOut.author — same reasoning, resolved by the route.
    author: str | None = None
    replies: list["PostOut"] = []


PostOut.model_rebuild()


def post_out_from_orm(post, my_vote: int = 0, author: str | None = None) -> "PostOut":
    """Build a PostOut from a Post ORM object using scalar columns only.

    Avoids `PostOut.model_validate(post)`, which would read the lazy
    `replies` relationship and trigger async IO outside the greenlet
    (MissingGreenlet). Callers assemble the reply tree themselves, and resolve
    `author` themselves for the same reason.
    """
    return PostOut(
        id=post.id,
        thread_id=post.thread_id,
        user_id=post.user_id,
        parent_id=post.parent_id,
        content=post.content,
        score=post.score,
        my_vote=my_vote,
        created_at=post.created_at,
        updated_at=post.updated_at,
        author=author,
        replies=[],
    )
