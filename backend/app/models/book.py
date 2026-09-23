import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_books_source_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'google_books'")
    )
    external_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str] = mapped_column(String(500), nullable=False)
    cover_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isbn_13: Mapped[str | None] = mapped_column(String(13), nullable=True, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_rating: Mapped[float | None] = mapped_column(Numeric(2, 1), nullable=True)
    ratings_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    maturity_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    info_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    preview_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    genre_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("genres.id", ondelete="SET NULL"), nullable=True, index=True
    )
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    # Relationships
    genre: Mapped["Genre | None"] = relationship("Genre", back_populates="books")  # noqa: F821
    work: Mapped["Work | None"] = relationship(  # noqa: F821
        "Work", back_populates="editions", foreign_keys=[work_id]
    )
    shelves: Mapped[list["Shelf"]] = relationship("Shelf", back_populates="book", cascade="all, delete-orphan")  # noqa: F821
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="book")  # noqa: F821
