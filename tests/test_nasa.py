"""Tests for the download's failure paths -- the whole reason it has a retry budget."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from moonback.nasa import DownloadError, backoff_delay, download

URL = "https://svs.gsfc.nasa.gov/frames/moon.0042.tif"
PAYLOAD = b"\x49\x49\x2a\x00fake tiff payload"


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def scripted(*outcomes: object) -> tuple[httpx.Client, list[httpx.Request]]:
    """A client that plays back ``outcomes`` in order; Exceptions are raised, Responses returned."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        outcome = outcomes[min(len(seen) - 1, len(outcomes) - 1)]
        if isinstance(outcome, Exception):
            outcome.request = request  # type: ignore[attr-defined]
            raise outcome
        assert isinstance(outcome, httpx.Response)
        return httpx.Response(outcome.status_code, content=outcome.content, headers=outcome.headers)

    return client_for(handler), seen


def no_sleep(_seconds: float) -> None:
    """Retry tests assert on attempt counts, not on wall clock."""


class TestBackoffDelay:
    @pytest.mark.parametrize(
        ("attempt", "ceiling"), [(0, 0.5), (1, 1.0), (2, 2.0), (3, 4.0), (4, 8.0), (9, 8.0)]
    )
    def test_doubles_up_to_a_cap(self, attempt: int, ceiling: float) -> None:
        assert backoff_delay(attempt, jitter=lambda: 1.0) == pytest.approx(ceiling)

    def test_full_jitter_spans_the_whole_window(self) -> None:
        # Every installation runs on the hour, so retries must not resynchronise.
        assert backoff_delay(3, jitter=lambda: 0.0) == 0.0
        assert backoff_delay(3, jitter=lambda: 0.5) == pytest.approx(2.0)

    def test_negative_attempt_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must not be negative"):
            backoff_delay(-1)


class TestDownloadFrame:
    def test_writes_the_payload_on_first_success(self, tmp_path: Path) -> None:
        client, seen = scripted(httpx.Response(200, content=PAYLOAD))
        destination = tmp_path / "moon.tif"

        download(client, URL, destination, sleep=no_sleep)

        assert destination.read_bytes() == PAYLOAD
        assert len(seen) == 1

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_retries_transient_server_failures_then_succeeds(
        self, tmp_path: Path, status: int
    ) -> None:
        client, seen = scripted(
            httpx.Response(status),
            httpx.Response(status),
            httpx.Response(200, content=PAYLOAD),
        )
        destination = tmp_path / "moon.tif"

        download(client, URL, destination, attempts=4, sleep=no_sleep)

        assert destination.read_bytes() == PAYLOAD
        assert len(seen) == 3

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(httpx.ReadTimeout("read timed out"), id="read-timeout"),
            pytest.param(httpx.ConnectTimeout("connect timed out"), id="connect-timeout"),
            pytest.param(httpx.ConnectError("refused"), id="connect-error"),
            pytest.param(httpx.RemoteProtocolError("truncated"), id="truncated-body"),
        ],
    )
    def test_retries_transport_failures(self, tmp_path: Path, error: Exception) -> None:
        client, seen = scripted(error, httpx.Response(200, content=PAYLOAD))
        destination = tmp_path / "moon.tif"

        download(client, URL, destination, attempts=3, sleep=no_sleep)

        assert destination.read_bytes() == PAYLOAD
        assert len(seen) == 2

    def test_gives_up_after_the_attempt_budget(self, tmp_path: Path) -> None:
        client, seen = scripted(httpx.Response(503))

        with pytest.raises(DownloadError, match="after 3 attempts"):
            download(client, URL, tmp_path / "moon.tif", attempts=3, sleep=no_sleep)

        assert len(seen) == 3, "a bounded budget, not an unbounded loop"

    def test_does_not_retry_a_404(self, tmp_path: Path) -> None:
        # A 404 means we asked for the wrong thing. Retrying cannot fix that,
        # and hammering a NASA host for it is rude.
        client, seen = scripted(httpx.Response(404))

        with pytest.raises(DownloadError, match="check the SVS id"):
            download(
                client,
                URL,
                tmp_path / "moon.tif",
                attempts=5,
                sleep=no_sleep,
                not_found_hint="check the SVS id",
            )

        assert len(seen) == 1, "a 404 costs exactly one request"

    def test_honours_retry_after_within_a_cap(self, tmp_path: Path) -> None:
        client, _ = scripted(
            httpx.Response(429, headers={"retry-after": "2"}),
            httpx.Response(429, headers={"retry-after": "9999"}),
            httpx.Response(200, content=PAYLOAD),
        )
        waits: list[float] = []

        download(
            client, URL, tmp_path / "moon.tif", attempts=4, sleep=waits.append, jitter=lambda: 1.0
        )

        # Second wait is clamped: a bad header must not park a scheduled task.
        assert waits == [2.0, 30.0]

    def test_leaves_no_partial_file_behind_on_failure(self, tmp_path: Path) -> None:
        client, _ = scripted(httpx.Response(500))
        destination = tmp_path / "moon.tif"

        with pytest.raises(DownloadError):
            download(client, URL, destination, attempts=2, sleep=no_sleep)

        assert list(tmp_path.iterdir()) == [], "a .part file would be fed to ImageMagick next run"

    def test_does_not_clobber_a_good_file_when_the_retry_fails(self, tmp_path: Path) -> None:
        destination = tmp_path / "moon.tif"
        destination.write_bytes(b"previous good frame")
        client, _ = scripted(httpx.Response(503))

        with pytest.raises(DownloadError):
            download(client, URL, destination, attempts=2, sleep=no_sleep)

        assert destination.read_bytes() == b"previous good frame"

    def test_a_truncated_retry_does_not_append_to_the_first_attempt(self, tmp_path: Path) -> None:
        client, _ = scripted(
            httpx.Response(200, content=b"first-attempt-bytes"),
            httpx.Response(200, content=PAYLOAD),
        )
        destination = tmp_path / "moon.tif"

        download(client, URL, destination, sleep=no_sleep)

        # Each attempt opens the .part file fresh, so nothing concatenates.
        assert destination.read_bytes() == b"first-attempt-bytes"

    def test_zero_attempts_is_a_programming_error(self, tmp_path: Path) -> None:
        client, _ = scripted(httpx.Response(200, content=PAYLOAD))

        with pytest.raises(ValueError, match="at least 1"):
            download(client, URL, tmp_path / "moon.tif", attempts=0)
