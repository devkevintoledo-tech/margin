import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class WorkSource(str, enum.Enum):
    """Where this work's identity came from."""

    openlibrary = "openlibrary"
    heuristic = "heuristic"


class WorkKind(str, enum.Enum):
    """Values match ``work_identity.classify_kind``'s return strings."""

    single = "single"
    collection = "collection"


class WorkProvenance(str, enum.Enum):
    """Which resolution tier produced the identity — isbn is the strongest."""

    isbn = "isbn"
    title_author = "title_author"
    heuristic = "heuristic"


class Work(Base):
    """A book as readers mean it: one work, many editions.

    ``books`` rows are editions of a work. Threads and shelves hang off the
    work, never the edition, so a discussion is never split across printings.
    """

    __tablename__ = "works"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_works_source_external_id"),
        Index("ix_works_search_doc", "search_doc", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source: Mapped[WorkSource] = mapped_column(
        Enum(WorkSource, name="work_source_enum"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Not identity for Open Library works — the bridge that lets a heuristic
    # work be recognised as the same book once a sibling edition resolves.
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str] = mapped_column(String(500), nullable=False)
    first_publish_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[WorkKind] = mapped_column(
        Enum(WorkKind, name="work_kind_enum"), nullable=False, default=WorkKind.single
    )
    identity_provenance: Mapped[WorkProvenance] = mapped_column(
        Enum(WorkProvenance, name="work_provenance_enum"), nullable=False
    )
    # Cover and description are read through this edition rather than copied,
    # so there is nothing to drift. Nullable both ways: insert work → attach
    # editions → set representative.
    # `use_alter` breaks the works↔books FK cycle: without it, create_all cannot
    # order the two CREATE TABLEs and raises CircularDependencyError. The
    # constraint is emitted as a separate ALTER instead.
    representative_book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "books.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_works_representative_book_id",
        ),
        nullable=True,
    )
    genre_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("genres.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # --- Open Library presentation and ranking data -------------------------
    # Cover precedence inverts here: OL's librarian-curated image wins over
    # Google's, which serves a placeholder PNG at HTTP 200 for metadata-only
    # records and so cannot be trusted.
    ol_cover_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # OL's edition total (26 for Red Rising), which is a fact about the book
    # and independent of how many editions we happen to have ingested.
    ol_edition_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    readinglog_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    ratings_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    # Space-joined OL subject tags. Indexed at weight C so a series sibling
    # (Iron Gold, tagged `franchise:Red Rising`) is findable by the series
    # name — without this the local index returns fewer results than the
    # upstream call that filled it.
    subjects: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Work-level description, filled by lazy enrichment. A work can exist with
    # zero editions, so it cannot always be read through a representative.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Generated, not maintained in Python: the database is the only writer, so
    # it can never drift from title/author/subjects. Declared here (not only in
    # the migration) because tests build the schema with create_all.
    search_doc: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(author, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(subjects, '')), 'C')",
            persisted=True,
        ),
        nullable=False,
    )
    # Tombstone pointer: a merged work keeps resolving so its URLs survive.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships. `foreign_keys` is required on both: works↔books has two
    # FK paths (books.work_id and works.representative_book_id).
    editions: Mapped[list["Book"]] = relationship(  # noqa: F821
        "Book", back_populates="work", foreign_keys="Book.work_id"
    )
    representative: Mapped["Book | None"] = relationship(  # noqa: F821
        "Book", foreign_keys=[representative_book_id], post_update=True
    )
    genre: Mapped["Genre | None"] = relationship("Genre", back_populates="works")  # noqa: F821
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="work")  # noqa: F821
    shelves: Mapped[list["Shelf"]] = relationship(  # noqa: F821
        "Shelf", back_populates="work", cascade="all, delete-orphan"
    )
