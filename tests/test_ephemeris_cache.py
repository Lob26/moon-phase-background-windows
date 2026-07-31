"""Fetch-on-miss: the ephemeris is a cache, so the January rollover self-heals.

Once a year's SVS id is known, the first hourly run of that year downloads the
table it needs. The Task Scheduler trigger that already exists is the only
scheduler involved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from moonback.__main__ import ensure_ephemeris
from moonback.config import PROFILES, Config
from moonback.nasa import DownloadError

from .conftest import build_mooninfo

TABLE = build_mooninfo(datetime(2026, 1, 1, tzinfo=UTC), 24)


def config_for(home: Path, year: int = 2026) -> Config:
    return Config(
        home=home,
        magick="magick",
        profile=PROFILES["standard"],
        year=year,
        connect_timeout=10.0,
        read_timeout=60.0,
        attempts=2,
        log_file=home / "mbg.log",
    )


def client_serving(*, body: str | None = None, status: int = 200) -> tuple[httpx.Client, list[str]]:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(status, content=(body or "").encode())

    return httpx.Client(transport=httpx.MockTransport(handler)), urls


class TestEnsureEphemeris:
    def test_downloads_and_caches_when_absent(self, tmp_path: Path) -> None:
        config = config_for(tmp_path)
        client, urls = client_serving(body=TABLE)

        path = ensure_ephemeris(client, config)

        assert path == tmp_path / "data" / "mooninfo_2026.txt"
        assert path.read_text(encoding="utf-8") == TABLE
        assert urls == [
            "https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/mooninfo_2026.txt"
        ]

    def test_creates_the_data_directory_on_a_bare_checkout(self, tmp_path: Path) -> None:
        config = config_for(tmp_path)
        assert not (tmp_path / "data").exists()
        client, _ = client_serving(body=TABLE)

        ensure_ephemeris(client, config)

        assert (tmp_path / "data" / "mooninfo_2026.txt").is_file()

    def test_does_not_refetch_when_already_cached(self, tmp_path: Path) -> None:
        config = config_for(tmp_path)
        cached = tmp_path / "data" / "mooninfo_2026.txt"
        cached.parent.mkdir()
        cached.write_text(TABLE, encoding="utf-8")
        client, urls = client_serving(body="SHOULD NOT BE FETCHED")

        path = ensure_ephemeris(client, config)

        assert urls == [], "the cache is only a miss once per year"
        assert path.read_text(encoding="utf-8") == TABLE

    def test_each_year_caches_separately(self, tmp_path: Path) -> None:
        client, urls = client_serving(body=TABLE)

        ensure_ephemeris(client, config_for(tmp_path, year=2025))
        ensure_ephemeris(client, config_for(tmp_path, year=2026))

        assert (tmp_path / "data" / "mooninfo_2025.txt").is_file()
        assert (tmp_path / "data" / "mooninfo_2026.txt").is_file()
        assert [u.rsplit("/", 2)[-2] for u in urls] == ["a005415", "a005587"]

    def test_a_404_blames_the_collection_id(self, tmp_path: Path) -> None:
        # The id is the only thing a human supplies here, so it is the only
        # thing worth pointing at.
        config = config_for(tmp_path)
        client, _ = client_serving(status=404)

        with pytest.raises(DownloadError, match="SVS collection id mapped for 2026"):
            ensure_ephemeris(client, config)

    def test_a_failed_fetch_leaves_no_cache_behind(self, tmp_path: Path) -> None:
        config = config_for(tmp_path)
        client, _ = client_serving(status=404)

        with pytest.raises(DownloadError):
            ensure_ephemeris(client, config)

        # A zero-byte cache file would poison every later run: the miss would
        # never happen again, and parsing would fail forever.
        assert not (tmp_path / "data" / "mooninfo_2026.txt").exists()
