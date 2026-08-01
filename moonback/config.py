"""Runtime configuration, resolved from the environment and validated up front.

Everything that can be wrong about the environment -- a missing ImageMagick, an
unmapped year, an absent ephemeris file -- is detected here, before a 4 MB
download happens, and reported with the exact remedy.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .layout import CORNERS
from .visibility import Observer

#: Written by setup_environment.ps1 from the answers given at install time.
#: Environment variables still win, so a one-off run can override anything.
SETTINGS_FILENAME = "moonback.toml"

#: Repo root: the ephemeris tables and canvas images live alongside the package.
DEFAULT_HOME = Path(__file__).resolve().parent.parent

#: NASA publishes one "Moon Phase and Libration" visualisation per year, each
#: under its own SVS id. A new year needs a new entry here plus the matching
#: ``data/mooninfo_<year>.txt``; see INSTALL.md ("Rolling over to a new year").
SVS_COLLECTIONS: dict[int, int] = {
    2025: 5415,
    2026: 5587,
}

SVS_FRAME_BASE = "https://svs.gsfc.nasa.gov/vis/a000000"


def svs_collection_url(collection: int) -> str:
    """Base URL for an SVS visualisation. Ids are bucketed by hundreds."""
    group = f"a{collection // 100 * 100:06d}"
    return f"{SVS_FRAME_BASE}/{group}/a{collection:06d}"


class ConfigError(Exception):
    """The environment cannot support a run. The message says how to fix it."""


@dataclass(frozen=True, slots=True)
class RenderProfile:
    """A canvas size and the NASA frame resolution that fits it."""

    name: str
    canvas: str
    canvas_width: int
    canvas_height: int
    frame_resolution: str
    point_size: int
    caption_margin: tuple[int, int]
    """Inset from whichever corner the caption is placed in, in canvas pixels."""


PROFILES: dict[str, RenderProfile] = {
    "standard": RenderProfile(
        name="standard",
        canvas="best_small.tif",
        canvas_width=5461,
        canvas_height=3640,
        frame_resolution="3840x2160_16x9_30p",
        point_size=50,
        # 620 from the bottom reproduces the original east/+1200 placement.
        caption_margin=(100, 620),
    ),
    "large": RenderProfile(
        name="large",
        canvas="best.tif",
        canvas_width=8192,
        canvas_height=5461,
        frame_resolution="5760x3240_16x9_30p",
        point_size=80,
        caption_margin=(150, 930),
    ),
}


class OnError:
    """What an hourly run should do when the work fails.

    Config errors always fail loudly regardless: they need a human, and hiding
    them would mean a wallpaper that quietly stopped updating months ago.
    """

    REPORT = "report"
    """Exit non-zero so Task Scheduler's Last Run Result shows the failure."""

    QUIET = "quiet"
    """Keep the previous wallpaper and exit 0. Still logged to mbg.log."""


@dataclass(frozen=True, slots=True)
class Config:
    home: Path
    magick: str
    profile: RenderProfile
    year: int
    connect_timeout: float
    read_timeout: float
    attempts: int
    log_file: Path
    on_error: str = OnError.REPORT
    observer: Observer | None = None
    caption_corner: str = "bottom-right"
    eclipse_imagery: bool = True
    """Swap in NASA's telescopic eclipse render while an eclipse is under way."""

    @property
    def ephemeris_path(self) -> Path:
        return self.home / "data" / f"mooninfo_{self.year}.txt"

    @property
    def eclipse_path(self) -> Path:
        return self.home / "data" / "lunar_eclipses.txt"

    @property
    def eclipse_view_path(self) -> Path:
        return self.home / "data" / "eclipse_views.txt"

    @property
    def canvas_path(self) -> Path:
        return self.home / self.profile.canvas

    @property
    def output_path(self) -> Path:
        return self.home / "back.tif"

    @property
    def _collection_url(self) -> str:
        return svs_collection_url(SVS_COLLECTIONS[self.year])

    @property
    def mooninfo_url(self) -> str:
        return f"{self._collection_url}/mooninfo_{self.year}.txt"

    def frame_url(self, filename: str) -> str:
        return (
            f"{self._collection_url}/frames/"
            f"{self.profile.frame_resolution}/plain/{filename}"
        )

    def eclipse_frame_url(self, svs_id: int, filename: str) -> str:
        """A frame from a per-eclipse telescopic sequence.

        Always 3840x2160: the SVS publishes these at one size, so the 'large'
        profile composites the same frame onto its bigger canvas.
        """
        return f"{svs_collection_url(svs_id)}/frames/3840x2160_16x9_30p/plain/{filename}"


def resolve_magick(explicit: str | None = None) -> str:
    """Locate the ImageMagick driver, or explain precisely how to supply it.

    ``MOONBACK_MAGICK`` may be either a bare command name to look up on PATH or
    an absolute path to ``magick.exe``. Resolving it here means a missing
    ImageMagick surfaces as one actionable line instead of a FileNotFoundError
    from deep inside subprocess.
    """
    candidate = explicit or os.environ.get("MOONBACK_MAGICK") or "magick"

    found = shutil.which(candidate)
    if found:
        return found

    path = Path(candidate)
    if path.is_file():
        return str(path)

    if explicit or os.environ.get("MOONBACK_MAGICK"):
        raise ConfigError(
            f"ImageMagick is configured as {candidate!r}, but that is neither a command on "
            f"PATH nor a file that exists. Fix the 'magick' entry in "
            f"{SETTINGS_FILENAME} (or MOONBACK_MAGICK) to point at magick.exe, e.g. "
            f'"C:\\Program Files\\ImageMagick-7.1.2-Q16-HDRI\\magick.exe". '
            f"Re-running setup_environment.ps1 will detect it for you."
        )
    raise ConfigError(
        "ImageMagick is required but 'magick' is not on PATH. Install it "
        "(winget install ImageMagick.ImageMagick) and reopen your shell, or set "
        'MOONBACK_MAGICK="C:\\Program Files\\ImageMagick-7.1.2-Q16-HDRI\\magick.exe".'
    )


def load_settings(home: Path) -> dict[str, object]:
    """Read moonback.toml, or return an empty mapping if there isn't one."""
    path = home / SETTINGS_FILENAME
    if not path.is_file():
        return {}
    try:
        # utf-8-sig, not tomllib.load's binary mode: PowerShell's Set-Content
        # and Notepad both write a UTF-8 BOM, which tomllib rejects outright.
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path} could not be read: {exc}") from exc


def _setting(settings: dict[str, object], name: str, key: str) -> object | None:
    """Environment first, then moonback.toml. Either may be absent."""
    raw = os.environ.get(name)
    return raw if raw is not None else settings.get(key)


def _as_float(value: object, name: str, default: float) -> float:
    if value is None:
        return default
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number, got {value!r}") from exc
    if number <= 0:
        raise ConfigError(f"{name} must be positive, got {number}")
    return number


def _as_int(value: object, name: str, default: int, *, minimum: int = 1) -> int:
    if value is None:
        return default
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc
    if number < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {number}")
    return number


_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}


def _as_bool(value: object, name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value  # TOML has real booleans; the environment does not.
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false, got {value!r}")


def _read_observer(settings: dict[str, object]) -> Observer | None:
    """Build the observer from [location], or None when no place was configured."""
    location = settings.get("location")
    if location is None:
        return None
    if not isinstance(location, dict):
        raise ConfigError("[location] in moonback.toml must be a table")

    missing = {"name", "latitude", "longitude"} - location.keys()
    if missing:
        raise ConfigError(
            f"[location] is missing {', '.join(sorted(missing))}; "
            f"delete the section to turn eclipse visibility off"
        )
    try:
        return Observer(
            name=str(location["name"]),
            latitude=float(location["latitude"]),  # type: ignore[arg-type]
            longitude=float(location["longitude"]),  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"[location] is not a usable place: {exc}") from exc


def load_config(now: datetime | None = None) -> Config:
    """Build a validated Config from the environment.

    ``now`` is injected so the default year is testable without freezing the clock.
    """
    now = now or datetime.now(UTC)

    home = Path(os.environ.get("MOONBACK_HOME", DEFAULT_HOME)).resolve()
    settings = load_settings(home)

    profile_name = (
        str(_setting(settings, "MOONBACK_PROFILE", "profile") or "standard").strip().lower()
    )
    if profile_name not in PROFILES:
        raise ConfigError(
            f"profile {profile_name!r} is not known; "
            f"choose one of {', '.join(sorted(PROFILES))} "
            f"(in {SETTINGS_FILENAME} or MOONBACK_PROFILE)"
        )

    on_error = (
        str(_setting(settings, "MOONBACK_ON_ERROR", "on_error") or OnError.REPORT).strip().lower()
    )
    if on_error not in {OnError.REPORT, OnError.QUIET}:
        raise ConfigError(
            f"on_error {on_error!r} is not known; choose {OnError.REPORT} or {OnError.QUIET} "
            f"(in {SETTINGS_FILENAME} or MOONBACK_ON_ERROR)"
        )

    corner = (
        str(_setting(settings, "MOONBACK_CAPTION_CORNER", "caption_corner") or "bottom-right")
        .strip()
        .lower()
    )
    if corner not in CORNERS:
        raise ConfigError(
            f"caption_corner {corner!r} is not known; choose one of {', '.join(CORNERS)} "
            f"(in {SETTINGS_FILENAME} or MOONBACK_CAPTION_CORNER)"
        )

    eclipse_imagery = _as_bool(
        _setting(settings, "MOONBACK_ECLIPSE_IMAGERY", "eclipse_imagery"),
        "eclipse_imagery",
        default=True,
    )

    year = _as_int(
        _setting(settings, "MOONBACK_YEAR", "year"),
        "year",
        now.astimezone(UTC).year,
        minimum=1900,
    )
    if year not in SVS_COLLECTIONS:
        raise ConfigError(
            f"No NASA visualisation is mapped for {year}. Find that year's "
            f"'Moon Phase and Libration' id at https://svs.gsfc.nasa.gov/gallery/moonphase/, "
            f"add it to SVS_COLLECTIONS in moonback/config.py, and save its "
            f"mooninfo_{year}.txt into data/. Mapped years: "
            f"{', '.join(str(y) for y in sorted(SVS_COLLECTIONS))}."
        )

    config = Config(
        home=home,
        magick=resolve_magick(str(_setting(settings, "MOONBACK_MAGICK", "magick") or "") or None),
        profile=PROFILES[profile_name],
        year=year,
        connect_timeout=_as_float(
            _setting(settings, "MOONBACK_CONNECT_TIMEOUT", "connect_timeout"),
            "connect_timeout",
            10.0,
        ),
        read_timeout=_as_float(
            _setting(settings, "MOONBACK_READ_TIMEOUT", "read_timeout"), "read_timeout", 60.0
        ),
        attempts=_as_int(_setting(settings, "MOONBACK_ATTEMPTS", "attempts"), "attempts", 4),
        log_file=Path(os.environ.get("MOONBACK_LOG_FILE", home / "mbg.log")),
        on_error=on_error,
        observer=_read_observer(settings),
        caption_corner=corner,
        eclipse_imagery=eclipse_imagery,
    )

    # The ephemeris is deliberately NOT checked here: it is a cache, fetched on
    # first miss (see moonback.__main__.ensure_ephemeris). The canvas is a real
    # prerequisite -- nothing can regenerate it -- so it is checked up front.
    if not config.canvas_path.is_file():
        raise ConfigError(f"canvas image not found: {config.canvas_path}")

    return config
