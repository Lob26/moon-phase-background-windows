"""moonback.toml: what the interactive installer writes and the tool reads back.

A scheduled task does not inherit the shell you tested in, which is why the
answers live in a file rather than in environment variables. Environment
variables still win, so a one-off run can override anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from moonback import config as config_module
from moonback.config import OnError, load_config, load_settings


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in list(config_module.os.environ):
        if name.startswith("MOONBACK_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config_module.shutil, "which", lambda name: rf"C:\bin\{name}.exe")
    (tmp_path / "best_small.tif").write_bytes(b"")
    (tmp_path / "best.tif").write_bytes(b"")
    monkeypatch.setenv("MOONBACK_HOME", str(tmp_path))
    return tmp_path


def write_settings(home: Path, body: str, *, bom: bool = False) -> None:
    encoding = "utf-8-sig" if bom else "utf-8"
    (home / "moonback.toml").write_text(body, encoding=encoding)


NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class TestLoadSettings:
    def test_absent_file_is_not_an_error(self, tmp_path: Path) -> None:
        assert load_settings(tmp_path) == {}

    def test_a_utf8_bom_is_tolerated(self, home: Path) -> None:
        # PowerShell's Set-Content and Notepad both write one, and tomllib
        # rejects it outright. Users edit this file by hand.
        write_settings(home, 'profile = "large"\n', bom=True)

        assert load_settings(home)["profile"] == "large"

    def test_malformed_toml_names_the_file(self, home: Path) -> None:
        write_settings(home, "profile = large\n")

        with pytest.raises(config_module.ConfigError, match="moonback.toml could not be read"):
            load_settings(home)


class TestSettingsDriveConfig:
    def test_values_are_read_from_the_file(self, home: Path) -> None:
        write_settings(
            home,
            'profile = "large"\non_error = "quiet"\nattempts = 7\nread_timeout = 12.5\n',
        )

        loaded = load_config(now=NOW)

        assert loaded.profile.name == "large"
        assert loaded.on_error == OnError.QUIET
        assert loaded.attempts == 7
        assert loaded.read_timeout == 12.5

    def test_the_environment_overrides_the_file(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_settings(home, 'profile = "large"\nattempts = 7\n')
        monkeypatch.setenv("MOONBACK_PROFILE", "standard")

        loaded = load_config(now=NOW)

        assert loaded.profile.name == "standard", "env wins"
        assert loaded.attempts == 7, "file still supplies what env does not"

    def test_defaults_apply_when_the_file_is_silent(self, home: Path) -> None:
        write_settings(home, 'profile = "large"\n')

        loaded = load_config(now=NOW)

        assert loaded.on_error == OnError.REPORT
        assert loaded.attempts == 4

    def test_an_unknown_on_error_lists_the_valid_ones(self, home: Path) -> None:
        write_settings(home, 'on_error = "explode"\n')

        with pytest.raises(config_module.ConfigError, match="report or quiet"):
            load_config(now=NOW)

    def test_magick_can_be_pinned_in_the_file(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = home / "magick.exe"
        exe.write_bytes(b"")
        monkeypatch.setattr(config_module.shutil, "which", lambda _name: None)
        write_settings(home, f'magick = "{exe.as_posix()}"\n')

        assert load_config(now=NOW).magick == str(exe)


class TestLocation:
    def test_no_location_section_means_no_observer(self, home: Path) -> None:
        write_settings(home, 'profile = "standard"\n')

        assert load_config(now=NOW).observer is None

    def test_a_configured_place_becomes_an_observer(self, home: Path) -> None:
        write_settings(
            home,
            '[location]\nname = "Bogota"\nlatitude = 4.71\nlongitude = -74.07\n',
        )

        observer = load_config(now=NOW).observer

        assert observer is not None
        assert (observer.name, observer.latitude, observer.longitude) == ("Bogota", 4.71, -74.07)

    @pytest.mark.parametrize(
        ("body", "missing"),
        [
            ('[location]\nlatitude = 4.71\nlongitude = -74.07\n', "name"),
            ('[location]\nname = "X"\nlongitude = -74.07\n', "latitude"),
            ('[location]\nname = "X"\nlatitude = 4.71\n', "longitude"),
        ],
    )
    def test_a_half_filled_location_is_refused(self, home: Path, body: str, missing: str) -> None:
        # Guessing a coordinate would put a confident, wrong claim on the screen.
        write_settings(home, body)

        with pytest.raises(config_module.ConfigError, match=missing):
            load_config(now=NOW)

    def test_an_impossible_coordinate_is_refused(self, home: Path) -> None:
        write_settings(home, '[location]\nname = "X"\nlatitude = 999\nlongitude = 0\n')

        with pytest.raises(config_module.ConfigError, match="not a usable place"):
            load_config(now=NOW)

    def test_location_must_be_a_table(self, home: Path) -> None:
        write_settings(home, 'location = "Bogota"\n')

        with pytest.raises(config_module.ConfigError, match="must be a table"):
            load_config(now=NOW)
