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
    expected = {"auth", "works", "genres", "series", "threads", "posts", "users"}
    assert expected == tag_names
    for tag in data["tags"]:
        assert tag.get("description"), f"Tag '{tag['name']}' has no description"
