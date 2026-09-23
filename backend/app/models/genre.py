import uuid

from sqlalchemy import String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    books: Mapped[list["Book"]] = relationship("Book", back_populates="genre")  # noqa: F821
    works: Mapped[list["Work"]] = relationship("Work", back_populates="genre")  # noqa: F821
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="genre")  # noqa: F821
