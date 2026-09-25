import uuid

from app.models import Work, WorkKind, WorkProvenance, WorkSource
from app.services.search import search_local


def make_work(title, author="Pierce Brown", **kw):
    base = dict(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key=f"{title.lower()}\x1f{author.lower()}",
        title=title,
        author=author,
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    base.update(kw)
    return Work(**base)


async def test_search_local_finds_a_work_by_title(db_session):
    db_session.add(make_work("Red Rising"))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising"]


async def test_famous_work_outranks_an_obscure_one_with_the_same_title(db_session):
    db_session.add(make_work("Red Rising", "Renee Joiner", readinglog_count=8))
    db_session.add(make_work("Red Rising", "Pierce Brown", readinglog_count=1036))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.author for w in found] == ["Pierce Brown", "Renee Joiner"]


async def test_an_irrelevant_famous_work_does_not_surface(db_session):
    db_session.add(make_work("Dune", "Frank Herbert", readinglog_count=4402))
    db_session.add(make_work("Red Rising", "Pierce Brown", readinglog_count=1036))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising"]


async def test_a_series_sibling_is_found_through_its_subjects(db_session):
    db_session.add(
        make_work("Iron Gold", subjects="franchise:Red Rising series:Red Rising Saga")
    )
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Iron Gold"]


async def test_a_title_match_outranks_a_subject_only_match(db_session):
    # Weight A over weight C: the book you named beats its series siblings.
    db_session.add(make_work("Iron Gold", subjects="franchise:Red Rising"))
    db_session.add(make_work("Red Rising"))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising", "Iron Gold"]


async def test_zero_readers_still_ranks_by_text_match(db_session):
    # The multiplier bottoms out at 1.0; it must never zero the text rank.
    db_session.add(make_work("Red Rising", readinglog_count=0))
    db_session.add(make_work("Unrelated Book", "Someone", readinglog_count=0))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising"]


async def test_collections_are_excluded(db_session):
    db_session.add(make_work("Red Rising Collection Set", kind=WorkKind.collection))
    db_session.add(make_work("Red Rising"))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising"]


async def test_merged_tombstones_are_excluded(db_session):
    target = make_work("Red Rising")
    db_session.add(target)
    await db_session.flush()
    tombstone = make_work("Red Rising", "Duplicate", merged_into_id=target.id)
    db_session.add(tombstone)
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.author for w in found] == ["Pierce Brown"]


async def test_blank_query_returns_nothing(db_session):
    db_session.add(make_work("Red Rising"))
    await db_session.flush()
    assert await search_local(db_session, "   ") == []
