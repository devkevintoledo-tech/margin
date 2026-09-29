"""OpenAPI metadata tests — no database required."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def test_openapi_tags_present():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    tag_names = {t["name"] for t in data.get("tags", [])}
    expected = {"auth", "works", "genres", "series", "threads", "posts", "users", "librarian"}
    assert expected == tag_names
    for tag in data["tags"]:
        assert tag.get("description"), f"Tag '{tag['name']}' has no description"


async def _schema() -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/openapi.json")
    assert resp.status_code == 200
    return resp.json()


def _ref_name(schema: dict) -> str | None:
    ref = schema.get("$ref", "")
    return ref.rsplit("/", 1)[-1] if ref else None


async def test_every_request_body_has_an_example():
    data = await _schema()
    components = data["components"]["schemas"]
    missing = set()
    for path, ops in data["paths"].items():
        for method, op in ops.items():
            body = op.get("requestBody", {}).get("content", {}).get("application/json")
            if not body:
                continue
            name = _ref_name(body["schema"])
            assert name, f"{method.upper()} {path} has an inline request body"
            if not components[name].get("examples"):
                missing.add(name)
    assert not missing, f"request bodies without examples: {sorted(missing)}"


async def test_auth_responses_have_examples():
    components = (await _schema())["components"]["schemas"]
    for name in ("Token", "UserOut", "MessageResponse"):
        assert components[name].get("examples"), f"{name} has no example"
