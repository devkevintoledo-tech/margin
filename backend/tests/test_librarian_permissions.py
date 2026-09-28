import pytest
from fastapi import HTTPException

from app.models import User
from app.services.auth import require_librarian
from scripts.grant_librarian import grant
from tests.librarian_factories import headers_for, make_user


async def test_me_reports_the_librarian_flag(client, db_session):
    user = await make_user(db_session, librarian=True)
    resp = await client.get("/api/auth/me", headers=headers_for(user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_librarian"] is True


async def test_require_librarian_refuses_readers(db_session):
    # Anonymous is refused upstream by get_current_user (401); Task 9 checks every
    # real route end to end. Here: the dependency itself.
    reader = await make_user(db_session)
    librarian = await make_user(db_session, librarian=True)
    with pytest.raises(HTTPException) as refused:
        await require_librarian(reader)
    assert refused.value.status_code == 403
    assert await require_librarian(librarian) is librarian


async def test_public_profile_does_not_reveal_the_flag(client, db_session):
    librarian = await make_user(db_session, librarian=True)
    body = (await client.get(f"/api/users/{librarian.username}")).json()
    assert "is_librarian" not in body


async def test_grant_and_revoke_are_idempotent(db_session):
    user = await make_user(db_session)
    assert await grant(db_session, user.username) is True
    assert await grant(db_session, user.username) is True
    assert (await db_session.get(User, user.id)).is_librarian is True
    assert await grant(db_session, user.username, revoke=True) is True
    assert (await db_session.get(User, user.id)).is_librarian is False


async def test_grant_unknown_username_fails(db_session):
    assert await grant(db_session, "nobody-by-this-name") is False
