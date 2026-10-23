"""
Network retry with backoff (extracted from assistant.py).
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Optional

import requests

TokenCallback = Callable[[str], None]
EventCallback = Callable[[str], None]

# HTTP status codes worth retrying: rate limit + transient server errors.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

class RetryableRequestError(Exception):
    """Raised when a request fails after all retry attempts are exhausted."""


def request_with_retry(
    method: str,
    url: str,
    max_retries: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    on_event: Optional[EventCallback] = None,
    **kwargs: Any,
) -> requests.Response:
    """
    Wraps requests.request with exponential backoff + jitter for 429/5xx errors.
    Honors a Retry-After header (seconds or HTTP-date) when the server sends one.
    Raises the underlying requests.HTTPError (via raise_for_status) if all
    retries are exhausted, or the original exception for non-retryable errors.
    """
    attempt = 0
    while True:
        try:
            response = requests.request(method, url, **kwargs)
        except requests.exceptions.RequestException as exc:
            # Network-level failure (timeout, connection error) - retry these too.
            attempt += 1
            if attempt > max_retries:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1))) + random.uniform(0, 1)
            if on_event:
                on_event(
                    f"Connection problem ({type(exc).__name__}); "
                    f"retrying in {delay:.1f}s (attempt {attempt}/{max_retries})"
                )
            time.sleep(delay)
            continue

        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response

        attempt += 1
        if attempt > max_retries:
            return response  # let the caller's raise_for_status() report the final failure

        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
        else:
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
        delay += random.uniform(0, 1)  # jitter to avoid thundering herd

        if on_event:
            reason = "rate limited (429)" if response.status_code == 429 else f"server error ({response.status_code})"
            on_event(f"{reason}; retrying in {delay:.1f}s (attempt {attempt}/{max_retries})")

        time.sleep(delay)
