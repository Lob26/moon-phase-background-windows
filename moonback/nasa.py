"""Downloading a single frame from NASA's SVS, with a timeout and a bounded retry budget.

The SVS host is a public, unfunded-for-your-use-case service that occasionally
stalls. Without a timeout a scheduled run can hang until the Task Scheduler's
72-hour limit; without a retry a single blip skips an hour of wallpaper. Both
are cheap to get right, so both are here.
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

#: Statuses worth trying again: transient server faults and explicit throttling.
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Cap on a server-supplied Retry-After, so a hostile or confused header cannot
#: park a scheduled task for hours.
MAX_RETRY_AFTER = 30.0


class DownloadError(Exception):
    """The frame could not be fetched within the retry budget."""


def backoff_delay(
    attempt: int,
    *,
    base: float = 0.5,
    cap: float = 8.0,
    jitter: Callable[[], float] = random.random,
) -> float:
    """Full-jitter exponential backoff for a zero-based ``attempt``.

    Full jitter (a uniform draw over the whole window) rather than a fixed
    delay: this task runs on the hour on every machine that installs it, so
    retries would otherwise resynchronise into a thundering herd against a
    NASA host that is doing us a favour.
    """
    if attempt < 0:
        raise ValueError(f"attempt must not be negative, got {attempt}")
    return min(cap, base * 2**attempt) * jitter()


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None  # HTTP-date form; fall back to our own backoff.
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER)


def download(
    client: httpx.Client,
    url: str,
    destination: Path,
    *,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
    not_found_hint: str = "the URL is wrong",
) -> Path:
    """Stream ``url`` to ``destination``, retrying transient failures.

    Each attempt streams into a sibling ``.part`` file that is only renamed over
    ``destination`` on success, so a failed or truncated attempt can never leave
    a half-written file for the next stage to choke on. ``sleep`` and ``jitter``
    are injected to keep the retry tests deterministic and instant.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be at least 1, got {attempts}")

    partial = destination.with_name(destination.name + ".part")
    last_error: Exception | None = None
    server_wait: float | None = None

    for attempt in range(attempts):
        if attempt:
            delay = (
                server_wait
                if server_wait is not None
                else backoff_delay(attempt - 1, jitter=jitter)
            )
            logger.warning(
                "Retrying %s in %.2fs (attempt %d/%d)", url, delay, attempt + 1, attempts
            )
            sleep(delay)

        server_wait = None
        try:
            with client.stream("GET", url) as response:
                if response.status_code in RETRYABLE_STATUSES:
                    response.read()
                    server_wait = _retry_after(response)
                    last_error = httpx.HTTPStatusError(
                        f"{response.status_code} from {url}",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()

                with open(partial, "wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        except httpx.HTTPStatusError as exc:
            # A 4xx means we asked for the wrong thing -- bad frame arithmetic or
            # a retired collection. Retrying cannot fix that, so fail now.
            partial.unlink(missing_ok=True)
            raise DownloadError(
                f"{url} returned {exc.response.status_code}; {not_found_hint}"
            ) from exc
        except httpx.TransportError as exc:
            partial.unlink(missing_ok=True)
            last_error = exc
            logger.warning(
                "Attempt %d/%d for %s failed: %s", attempt + 1, attempts, url, exc
            )
            continue

        os.replace(partial, destination)
        logger.debug("Downloaded %s to %s", url, destination)
        return destination

    partial.unlink(missing_ok=True)
    raise DownloadError(f"giving up on {url} after {attempts} attempts") from last_error
