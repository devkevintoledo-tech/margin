from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ThreadCreate(BaseModel):
    # Accept the frontend's payload as-is: genre threads are created by `slug`
    # and the opening post body arrives as `content`.
    model_config = ConfigDict(populate_by_name=True)

    title: str
    book_id: UUID | None = None
    genre_id: UUID | None = None
    genre_slug: str | None = None
    body: str | None = Field(default=None, alias="content")

    @model_validator(mode="after")
    def exactly_one_target(self) -> "ThreadCreate":
        has_book = self.book_id is not None
        has_genre = self.genre_id is not None or self.genre_slug is not None
        if has_book == has_genre:  # both set or neither set
            raise ValueError(
                "Exactly one of book_id or genre (genre_slug/genre_id) must be provided."
            )
        return self


class ThreadOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    title: str
    user_id: UUID
    book_id: UUID | None
    genre_id: UUID | None
    score: int
    created_at: datetime


class ThreadSummary(BaseModel):
    """List-view shape consumed by the frontend ThreadCard."""

    model_config = {"from_attributes": True}

    id: UUID
    title: str
    score: int
    post_count: int
    author: str
    genre_slug: str | None = None
    book_id: UUID | None = None


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
    created_at: datetime
    updated_at: datetime
    replies: list["PostOut"] = []


PostOut.model_rebuild()


def post_out_from_orm(post) -> "PostOut":
    """Build a PostOut from a Post ORM object using scalar columns only.

    Avoids `PostOut.model_validate(post)`, which would read the lazy
    `replies` relationship and trigger async IO outside the greenlet
    (MissingGreenlet). Callers assemble the reply tree themselves.
    """
    return PostOut(
        id=post.id,
        thread_id=post.thread_id,
        user_id=post.user_id,
        parent_id=post.parent_id,
        content=post.content,
        score=post.score,
        created_at=post.created_at,
        updated_at=post.updated_at,
        replies=[],
    )
