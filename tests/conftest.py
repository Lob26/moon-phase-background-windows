from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from moonback.moondata import MoonHour


def make_hour(
    at: datetime,
    illumination_pct: float = 50.0,
    cycle_age_days: float = 7.0,
    *,
    ra: float = 12.0,
    dec: float = 0.0,
    distance_km: float = 384_400.0,
) -> MoonHour:
    """A MoonHour for tests that only care about some of its fields."""
    return MoonHour(
        at=at,
        illumination_pct=illumination_pct,
        cycle_age_days=cycle_age_days,
        distance_km=distance_km,
        right_ascension_hours=ra,
        declination_degrees=dec,
    )

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Applied per module so the marker cannot drift from the file it describes.
_GROUPS = {
    "test_moondata": "astronomy",
    "test_eclipses": "astronomy",
    "test_eclipse_views": "astronomy",
    "test_visibility": "astronomy",
    "test_nasa": "plumbing",
    "test_config": "plumbing",
    "test_settings_file": "plumbing",
    "test_ephemeris_cache": "plumbing",
    "test_layout": "rendering",
    "test_events": "astronomy",
    "test_monitors": "rendering",
    "test_wallpaper": "rendering",
}


def pytest_collection_modifyitems(items) -> None:
    for item in items:
        group = _GROUPS.get(Path(str(item.fspath)).stem)
        if group:
            item.add_marker(getattr(pytest.mark, group))

_HEADER = (
    "   Date       Time    Phase    Age    Diam    Dist     RA        Dec"
    "      Slon      Slat     Elon     Elat   AxisA"
)

# Spelled out rather than via strftime("%b"): month abbreviations there follow
# LC_TIME, and these fixtures must not change meaning on a Spanish-locale box.
_MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)  # fmt: skip


def build_mooninfo(start: datetime, hours: int, *, phase: float = 50.0, age: float = 7.0) -> str:
    """Render a NASA-format ephemeris table, for tests that need a table they control."""
    lines = [_HEADER]
    for offset in range(hours):
        at = start + timedelta(hours=offset)
        stamp = f"{at.day:02d} {_MONTH_ABBR[at.month - 1]} {at.year} {at.hour:02d}:{at.minute:02d}"
        lines.append(
            f"{stamp} UT  {phase + offset:6.2f}  {age + offset:7.3f}"
            f"  1877.5  381744  19.7533   -21.0    100.0    1.0    1.0    1.0   10.0"
        )
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="session")
def real_2026_text() -> str:
    """The genuine NASA table shipped in the repo -- the data the tool actually runs on."""
    return (REPO_ROOT / "data" / "mooninfo_2026.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def real_2025_text() -> str:
    return (REPO_ROOT / "data" / "mooninfo_2025.txt").read_text(encoding="utf-8")
