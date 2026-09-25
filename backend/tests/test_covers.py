import respx
from httpx import Response

from app.services.covers import verify

REAL = "https://books.google.com/books/content?id=vSCbAwAAQBAJ"
FAKE = "https://books.google.com/books/content?id=5tDS0AEACAAJ"


@respx.mock
async def test_verify_rejects_googles_placeholder():
    # The live placeholder: a fixed 9103-byte PNG served at HTTP 200.
    respx.head(FAKE).mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )
    assert await verify([FAKE]) == set()


@respx.mock
async def test_verify_keeps_a_real_cover():
    respx.head(REAL).mock(
        return_value=Response(
            200, headers={"content-type": "image/jpeg", "content-length": "401823"}
        )
    )
    assert await verify([REAL]) == {REAL}


@respx.mock
async def test_verify_keeps_a_png_of_a_different_size():
    # Both conditions must hold; a legitimate PNG cover is not a placeholder.
    respx.head(REAL).mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "51200"}
        )
    )
    assert await verify([REAL]) == {REAL}


@respx.mock
async def test_verify_rejects_a_dead_url():
    respx.head(FAKE).mock(return_value=Response(404))
    assert await verify([FAKE]) == set()


@respx.mock
async def test_verify_rejects_on_transport_error():
    import httpx

    respx.head(FAKE).mock(side_effect=httpx.ConnectError("boom"))
    assert await verify([FAKE]) == set()


@respx.mock
async def test_verify_checks_many_urls():
    respx.head(REAL).mock(
        return_value=Response(200, headers={"content-type": "image/jpeg"})
    )
    respx.head(FAKE).mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )
    assert await verify([REAL, FAKE]) == {REAL}


async def test_verify_of_nothing_is_empty():
    assert await verify([]) == set()
