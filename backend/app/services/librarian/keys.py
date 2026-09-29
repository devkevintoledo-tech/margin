"""How app rows are named in pipeline/overrides (spec §5.1).

A fix is exportable only when every row it names has a key the next build
holds. Otherwise it applies in the app and is reported as runtime-only, with the
first missing key as the reason.
"""

from typing import Callable

from app.models import Book, Series, SeriesKind, Work, WorkSource


class MissingKey(Exception):
    pass


def work_key(work: Work) -> str:
    if work.source is WorkSource.openlibrary:
        return work.external_id  # includes a split's OL…W~OL…M
    raise MissingKey(f"{work.title} has no Open Library id (heuristic work)")


def edition_key(book: Book) -> str:
    if book.source == "openlibrary":
        return book.external_id
    raise MissingKey(f"edition {book.external_id} of {book.title} is a Google Books volume")


def series_key_of(series: Series) -> str:
    if series.kind is SeriesKind.singleton:
        raise MissingKey(f"{series.name} is a single book's page, not a series")
    if series.external_id.startswith(("wd:", "ol:")):
        return series.external_id
    return f"ol:{series.canonical_key}"


def release_series_key(series: Series) -> str:
    """The key of a series the next build is known to hold.

    rename, reject and remove fail the pipeline build for a series it does not
    know (overrides._check_target); only set_series can create one.
    """
    if series.catalog_release is None:
        raise MissingKey(f"{series.name} is not in a catalog release")
    return series_key_of(series)


def exported(build: Callable[[], list[dict]]) -> tuple[list[dict] | None, str | None]:
    """``(entries, None)``, or ``(None, reason)`` when a key is missing."""
    try:
        return build(), None
    except MissingKey as exc:
        return None, str(exc)
