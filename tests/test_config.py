"""Tests for the fail-loudly-up-front contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from moonback import config as config_module
from moonback.config import (
    PROFILES,
    SVS_COLLECTIONS,
    Config,
    ConfigError,
    load_config,
    resolve_magick,
)


class TestResolveMagick:
    def test_finds_a_command_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.shutil, "which", lambda name: rf"C:\bin\{name}.exe")

        assert resolve_magick() == r"C:\bin\magick.exe"

    def test_accepts_an_absolute_path_from_the_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        exe = tmp_path / "magick.exe"
        exe.write_bytes(b"")
        monkeypatch.setattr(config_module.shutil, "which", lambda _name: None)
        monkeypatch.setenv("MOONBACK_MAGICK", str(exe))

        assert resolve_magick() == str(exe)

    def test_missing_from_path_names_the_remedy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.shutil, "which", lambda _name: None)
        monkeypatch.delenv("MOONBACK_MAGICK", raising=False)

        with pytest.raises(ConfigError) as caught:
            resolve_magick()

        message = str(caught.value)
        assert "not on PATH" in message
        assert "MOONBACK_MAGICK" in message, "the error must say how to fix it"

    def test_a_bad_env_override_is_reported_as_such(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.shutil, "which", lambda _name: None)
        monkeypatch.setenv("MOONBACK_MAGICK", r"C:\nope\magick.exe")

        with pytest.raises(ConfigError, match=r"ImageMagick is configured as"):
            resolve_magick()


def _config(**overrides: object) -> Config:
    defaults: dict[str, object] = {
        "home": Path("/repo"),
        "magick": "magick",
        "profile": PROFILES["standard"],
        "year": 2026,
        "connect_timeout": 10.0,
        "read_timeout": 60.0,
        "attempts": 4,
        "log_file": Path("/repo/mbg.log"),
    }
    return Config(**(defaults | overrides))  # type: ignore[arg-type]


class TestFrameUrl:
    @pytest.mark.parametrize(
        ("year", "expected"),
        [
            (2025, "https://svs.gsfc.nasa.gov/vis/a000000/a005400/a005415/frames/"
                   "3840x2160_16x9_30p/plain/moon.0001.tif"),
            (2026, "https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/frames/"
                   "3840x2160_16x9_30p/plain/moon.0001.tif"),
        ],
    )
    def test_derives_the_svs_directory_grouping(self, year: int, expected: str) -> None:
        # SVS buckets ids by hundreds: 5415 lives under a005400, 5587 under a005500.
        assert _config(year=year).frame_url("moon.0001.tif") == expected

    def test_the_large_profile_asks_for_the_larger_frames(self) -> None:
        url = _config(profile=PROFILES["large"]).frame_url("moon.0001.tif")

        assert "5760x3240_16x9_30p" in url

    @pytest.mark.parametrize("year", sorted(SVS_COLLECTIONS))
    def test_every_mapped_year_has_a_well_formed_mooninfo_url(self, year: int) -> None:
        url = _config(year=year).mooninfo_url

        assert url.startswith("https://svs.gsfc.nasa.gov/vis/a000000/a00")
        assert url.endswith(f"/mooninfo_{year}.txt")


class TestLoadConfig:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in list(config_module.os.environ):
            if name.startswith("MOONBACK_"):
                monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(config_module.shutil, "which", lambda name: rf"C:\bin\{name}.exe")

    def test_defaults_to_the_current_utc_year(self) -> None:
        loaded = load_config(now=datetime(2026, 7, 31, 12, tzinfo=UTC))

        assert loaded.year == 2026
        assert loaded.profile.name == "standard"
        assert loaded.attempts == 4

    def test_an_unmapped_year_explains_the_yearly_rollover(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MOONBACK_YEAR", "2099")

        with pytest.raises(ConfigError) as caught:
            load_config()

        message = str(caught.value)
        assert "SVS_COLLECTIONS" in message
        assert "mooninfo_2099.txt" in message

    def test_an_unknown_profile_lists_the_valid_ones(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOONBACK_PROFILE", "gigantic")

        with pytest.raises(ConfigError, match="large, standard"):
            load_config()

    @pytest.mark.parametrize(
        ("name", "value", "expected"),
        [
            ("MOONBACK_CONNECT_TIMEOUT", "abc", "must be a number"),
            ("MOONBACK_CONNECT_TIMEOUT", "0", "must be positive"),
            ("MOONBACK_READ_TIMEOUT", "-5", "must be positive"),
            ("MOONBACK_ATTEMPTS", "0", "must be at least 1"),
            ("MOONBACK_ATTEMPTS", "many", "must be an integer"),
        ],
    )
    def test_rejects_nonsense_tuning_values(
        self, monkeypatch: pytest.MonkeyPatch, name: str, value: str, expected: str
    ) -> None:
        monkeypatch.setenv(name, value)

        with pytest.raises(ConfigError, match=expected):
            load_config()

    def test_a_missing_canvas_is_caught_before_any_download(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MOONBACK_HOME", str(tmp_path))

        with pytest.raises(ConfigError, match="canvas image not found"):
            load_config(now=datetime(2026, 7, 31, tzinfo=UTC))

    def test_a_missing_ephemeris_is_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # It is a cache, fetched on miss -- unlike the canvas, which nothing
        # can regenerate. Treating it as fatal would break the self-healing
        # January rollover.
        (tmp_path / "best_small.tif").write_bytes(b"")
        monkeypatch.setenv("MOONBACK_HOME", str(tmp_path))

        loaded = load_config(now=datetime(2026, 7, 31, tzinfo=UTC))

        assert not loaded.ephemeris_path.exists()
        assert loaded.mooninfo_url.endswith("/a005587/mooninfo_2026.txt")


class TestMonitorOutputs:
    def test_numbered_from_one_in_plan_order(self) -> None:
        config = _config(home=Path("/repo"))

        assert config.monitor_output_path(1).name == "back-1.tif"
        assert config.monitor_output_path(2).name == "back-2.tif"

    def test_stale_outputs_never_include_the_single_monitor_image(
        self, tmp_path: Path
    ) -> None:
        # back.tif is what the fallback and --at write. The dash in the glob is
        # the only thing keeping a per-monitor cleanup from deleting it.
        for name in ("back.tif", "back-1.tif", "back-2.tif", "back-7.tif"):
            (tmp_path / name).write_bytes(b"")
        config = _config(home=tmp_path)

        stale = config.stale_monitor_outputs({tmp_path / "back-1.tif", tmp_path / "back-2.tif"})

        assert [p.name for p in stale] == ["back-7.tif"]

    def test_nothing_is_stale_when_every_output_is_live(self, tmp_path: Path) -> None:
        (tmp_path / "back-1.tif").write_bytes(b"")
        config = _config(home=tmp_path)

        assert config.stale_monitor_outputs({tmp_path / "back-1.tif"}) == []
