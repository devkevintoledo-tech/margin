"""Series writes: the only module that inserts or moves ``series`` rows.

A work's room is decided here. Detection rules live in ``series_identity``;
this module applies them against the database.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import Series, SeriesKind, SeriesSource, Work
from app.services.series_identity import series_key, slugify


def singleton_series_for(work: Work) -> Series:
    """A series of one for ``work``.

    The slug carries a short id so it needs no uniqueness query — three
    different books are titled plain "Dune" — which is what lets this run
    inside a flush.
    """
    if work.id is None:
        work.id = uuid.uuid4()
    series_id = uuid.uuid4()
    return Series(
        id=series_id,
        source=SeriesSource.heuristic,
        external_id=f"singleton:{work.id}",
        name=work.title,
        slug=f"{slugify(work.title, max_length=60)}-{series_id.hex[:6]}",
        canonical_key=series_key(work.title),
        kind=SeriesKind.singleton,
    )


@event.listens_for(Session, "before_flush")
def _every_work_has_a_series(session, flush_context, instances) -> None:
    """Give any new work that arrives without a room a singleton of its own.

    This is the column default for a required foreign key that has to create
    its target. Checking ``__dict__`` rather than ``work.series`` avoids
    triggering a relationship load in the middle of a flush.
    """
    for obj in list(session.new):
        if (
            isinstance(obj, Work)
            and obj.series_id is None
            and obj.__dict__.get("series") is None
        ):
            obj.series = singleton_series_for(obj)
