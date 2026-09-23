import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ShelfStatus(str, enum.Enum):
    want_to_read = "want_to_read"
    reading = "reading"
    read = "read"


class Shelf(Base):
    __tablename__ = "shelves"
    __table_args__ = (UniqueConstraint("user_id", "book_id", name="uq_shelf_user_book"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable for the duration of the works migration: a shelf row created
    # after the cutover knows only its work. The column goes away entirely in
    # the second migration.
    book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), nullable=True, index=True
    )
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[ShelfStatus] = mapped_column(
        Enum(ShelfStatus, name="shelf_status_enum"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="shelves")  # noqa: F821
    book: Mapped["Book | None"] = relationship("Book", back_populates="shelves")  # noqa: F821
    work: Mapped["Work | None"] = relationship("Work", back_populates="shelves")  # noqa: F821
