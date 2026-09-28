"""Retry policy shared by every fetch."""

from __future__ import annotations

from typing import Callable, TypeVar

import httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
T = TypeVar("T")


class RetryableError(RuntimeError):
    """A failure worth another attempt: a 5xx/429, a dropped connection, a truncated stream."""


def with_retries(action: Callable[[], T], *, attempts: int, sleep: Callable[[float], None],
                 give_up: Callable[[Exception], Exception]) -> T:
    """Run ``action``, backing off 1s, 2s, 4s… between retryable failures."""
    for attempt in range(attempts):
        try:
            return action()
        except (RetryableError, httpx.TransportError) as exc:
            if attempt == attempts - 1:
                raise give_up(exc) from exc
            sleep(2 ** attempt)
    raise AssertionError("unreachable")


def check_status(response: httpx.Response) -> None:
    if response.status_code in RETRYABLE_STATUS:
        raise RetryableError(f"HTTP {response.status_code} from {response.url}")
    response.raise_for_status()
