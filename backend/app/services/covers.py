"""Tells a real cover from Google's placeholder.

Google Books returns ``imageLinks`` for metadata-only catalog records that have
no cover, then serves a placeholder image at HTTP 200 — so nothing in the JSON
distinguishes a real cover from a missing one, and only the bytes can. The
placeholder is a fixed asset: ``image/png``, exactly 9103 bytes, where real
covers are JPEG. Both conditions must hold, so a legitimate PNG cover survives.

This costs one HEAD per URL, which is why it runs during lazy enrichment and
never on the search path.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

import httpx

_TIMEOUT = 10.0
_PLACEHOLDER_TYPE = "image/png"
_PLACEHOLDER_BYTES = "9103"


async def _is_real(client: httpx.AsyncClient, url: str) -> bool:
    try:
        response = await client.head(url, follow_redirects=True)
    except httpx.RequestError:
        return False
    if response.status_code != 200:
        return False
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    length = response.headers.get("content-length", "")
    if content_type == _PLACEHOLDER_TYPE and length == _PLACEHOLDER_BYTES:
        return False
    return content_type.startswith("image/")


async def verify(urls: Sequence[str]) -> set[str]:
    """Return the subset of ``urls`` that are real cover images.

    Never raises: an unreachable cover is simply not a cover.
    """
    unique = [u for u in dict.fromkeys(urls) if u]
    if not unique:
        return set()

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        verdicts = await asyncio.gather(*(_is_real(client, u) for u in unique))
    return {url for url, ok in zip(unique, verdicts) if ok}
