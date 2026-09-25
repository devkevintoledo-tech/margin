"""Shelf model and API tests."""
import uuid
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.shelf import Shelf, ShelfStatus
from app.models.user import User, AuthProvider


# ---------------------------------------------------------------------------
# DB-level tests
# ---------------------------------------------------------------------------


async def test_shelf_db_rejects_duplicate_user_work(db_session, work):
    """The DB uniqueness constraint must fire even if app-layer check is bypassed."""
    user = User(
        email=f"u{uuid.uuid4().hex[:6]}@test.com",
        username=f"u{uuid.uuid4().hex[:6]}",
        password_hash="x",
        auth_provider=AuthProvider.email,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(Shelf(user_id=user.id, work_id=work.id, status=ShelfStatus.want_to_read))
    await db_session.flush()

    db_session.add(Shelf(user_id=user.id, work_id=work.id, status=ShelfStatus.reading))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# --- API tests ---


async def test_add_work_to_shelf(client, auth_headers, work):
    resp = await client.post(
        f"/api/works/{work.id}/shelf",
        json={"status": "want_to_read"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "want_to_read"
    assert body["work_id"] == str(work.id)


async def test_add_duplicate_shelf_returns_409(client, auth_headers, work):
    r1 = await client.post(
        f"/api/works/{work.id}/shelf",
        json={"status": "want_to_read"},
        headers=auth_headers,
    )
    assert r1.status_code == 201, r1.text
    resp = await client.post(
        f"/api/works/{work.id}/shelf",
        json={"status": "reading"},
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text


async def test_update_shelf_status(client, auth_headers, work):
    r1 = await client.post(
        f"/api/works/{work.id}/shelf",
        json={"status": "want_to_read"},
        headers=auth_headers,
    )
    assert r1.status_code == 201, r1.text
    resp = await client.put(
        f"/api/works/{work.id}/shelf",
        json={"status": "read"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "read"


async def test_update_nonexistent_shelf_returns_404(client, auth_headers, work):
    resp = await client.put(
        f"/api/works/{work.id}/shelf",
        json={"status": "read"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_remove_from_shelf(client, auth_headers, work):
    r1 = await client.post(
        f"/api/works/{work.id}/shelf",
        json={"status": "reading"},
        headers=auth_headers,
    )
    assert r1.status_code == 201, r1.text
    resp = await client.delete(f"/api/works/{work.id}/shelf", headers=auth_headers)
    assert resp.status_code == 204

    update = await client.put(
        f"/api/works/{work.id}/shelf",
        json={"status": "read"},
        headers=auth_headers,
    )
    assert update.status_code == 404


async def test_shelf_requires_auth(client, work):
    resp = await client.post(
        f"/api/works/{work.id}/shelf",
        json={"status": "want_to_read"},
    )
    assert resp.status_code in (401, 403)


async def test_shelf_post_and_put_have_documented_response_model(client):
    """POST and PUT shelf routes must declare a response_model so OpenAPI
    documents the shape with a $ref to ShelfOut (not an empty schema {}).
    Without response_model, FastAPI emits schema: {} — no field documentation."""
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()

    post_response_schema = (
        schema["paths"]["/api/works/{work_id}/shelf"]["post"]
        ["responses"]["201"]["content"]["application/json"]["schema"]
    )
    assert "$ref" in post_response_schema or "properties" in post_response_schema, post_response_schema

    put_response_schema = (
        schema["paths"]["/api/works/{work_id}/shelf"]["put"]
        ["responses"]["200"]["content"]["application/json"]["schema"]
    )
    assert "$ref" in put_response_schema or "properties" in put_response_schema, put_response_schema
