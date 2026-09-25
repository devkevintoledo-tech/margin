import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SearchQuery(Base):
    """A query that has already been resolved against Open Library.

    This row is what makes search local: its presence means the catalog
    already holds everything upstream would return for this query, so the
    request is answered from Postgres and no HTTP call is made. A query is
    paid for once, by one user, and every later search for it is free.
    """

    __tablename__ = "search_queries"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Normalized with google_books.normalize so "Red Rising" and "red  rising"
    # are one row.
    normalized_query: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, index=True
    )
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
