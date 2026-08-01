"""Pure moon-data logic: parsing NASA's ephemeris table and locating the current hour.

Nothing in this module touches the network, the filesystem or the clock. Every
function is a total function of its arguments, which is what makes the awkward
part of this project -- mapping "now" onto a NASA frame number -- testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

#: NASA publishes one frame per hour of the year, numbered from 1.
FIRST_FRAME_NUMBER = 1

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}  # fmt: skip

# "01 Jan 2026 00:00 UT  91.40  11.928  1985.1 ..." -- we only need the first
# two data columns, but the leading timestamp is what lets us verify our index.
# The month alternation is built from _MONTHS so an unrecognised month fails to
# match (and is reported as unparsable) rather than raising KeyError below.
_ROW = re.compile(
    r"""^\s*
    (?P<day>\d{1,2})\s+(?P<month>MONTHS)\s+(?P<year>\d{4})\s+
    (?P<hour>\d{2}):(?P<minute>\d{2})\s+UT\s+
    (?P<phase>\d+(?:\.\d+)?)\s+(?P<age>\d+(?:\.\d+)?)\s+
    (?P<diameter>\d+(?:\.\d+)?)\s+(?P<distance>\d+(?:\.\d+)?)\s+
    (?P<ra>-?\d+(?:\.\d+)?)\s+(?P<dec>-?\d+(?:\.\d+)?)\b
    """.replace("MONTHS", "|".join(_MONTHS)),
    re.VERBOSE,
)


class MoonDataError(Exception):
    """The ephemeris table is missing, malformed, or does not cover the moment asked for."""


@dataclass(frozen=True, slots=True)
class MoonHour:
    """One hourly row of NASA's ephemeris."""

    at: datetime
    """The UTC hour this row describes."""

    illumination_pct: float
    """Percent of the visible disc that is lit, 0-100."""

    cycle_age_days: float
    """Days elapsed since the last new moon."""

    distance_km: float
    """Centre-to-centre distance to the Moon."""

    right_ascension_hours: float
    """Geocentric apparent right ascension, in hours (0-24)."""

    declination_degrees: float
    """Geocentric apparent declination, in degrees."""

    @property
    def label(self) -> str:
        """The caption drawn onto the wallpaper."""
        return f"Phase: {self.illumination_pct:.2f}% Days: {self.cycle_age_days:.3f}"


def format_caption(hour: MoonHour, *notes: str | None) -> str:
    """The caption drawn onto the wallpaper, plus any extra clauses.

    Takes several because a night can be more than one thing at once: the full
    moon of 2026-05-31 is both a micromoon and a blue moon, and an eclipse can
    coincide with a supermoon.
    """
    return " - ".join([hour.label, *(note for note in notes if note)])


def parse_mooninfo(text: str) -> tuple[MoonHour, ...]:
    """Parse a NASA ``mooninfo_<year>.txt`` table into hourly rows.

    The file carries a one-line header and 8760 (or 8784, in a leap year) fixed
    width data rows. Lines that do not look like data rows are skipped, so the
    header needs no special casing; a file that yields no rows at all is an
    error rather than an empty result, because silently rendering a wallpaper
    with no caption is worse than not rendering one.
    """
    rows: list[MoonHour] = []
    for line in text.splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        fields = match.groupdict()
        rows.append(
            MoonHour(
                at=datetime(
                    int(fields["year"]),
                    _MONTHS[fields["month"]],
                    int(fields["day"]),
                    int(fields["hour"]),
                    int(fields["minute"]),
                    tzinfo=UTC,
                ),
                illumination_pct=float(fields["phase"]),
                cycle_age_days=float(fields["age"]),
                distance_km=float(fields["distance"]),
                right_ascension_hours=float(fields["ra"]),
                declination_degrees=float(fields["dec"]),
            )
        )

    if not rows:
        raise MoonDataError("ephemeris table contained no parsable data rows")
    return tuple(rows)


def hour_index(moment: datetime) -> int:
    """Return the zero-based index of ``moment`` among the hours of its own year.

    ``moment`` must be timezone-aware; it is converted to UTC first. NASA's
    frames are indexed in UTC, so using a naive local timestamp here silently
    shifts the wallpaper by the machine's UTC offset.
    """
    if moment.tzinfo is None:
        raise MoonDataError(
            "hour_index requires a timezone-aware datetime; "
            "NASA indexes frames in UTC and a naive local time would be off by the UTC offset"
        )
    moment = moment.astimezone(UTC)
    return (moment.timetuple().tm_yday - 1) * 24 + moment.hour


def frame_number(index: int) -> int:
    """Map a zero-based hour index onto NASA's one-based frame number."""
    if index < 0:
        raise MoonDataError(f"hour index must not be negative, got {index}")
    return index + FIRST_FRAME_NUMBER


def frame_filename(index: int) -> str:
    """The NASA filename for a zero-based hour index, e.g. ``moon.0001.tif``."""
    return f"moon.{frame_number(index):04d}.tif"


def select_hour(rows: tuple[MoonHour, ...], moment: datetime) -> tuple[MoonHour, int]:
    """Return the ephemeris row for ``moment`` and its zero-based index.

    The row's own timestamp is checked against the truncated ``moment``. That
    check is the point of this function: an off-by-one in the index arithmetic
    produces a plausible-looking wallpaper that is quietly a day out of date,
    and only comparing against the data's own clock catches it.
    """
    index = hour_index(moment)
    expected = moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)

    if index >= len(rows):
        raise MoonDataError(
            f"ephemeris covers {len(rows)} hours but {expected:%Y-%m-%d %H:%M UTC} "
            f"is hour {index} of the year"
        )

    row = rows[index]
    if row.at != expected:
        raise MoonDataError(
            f"ephemeris row {index} is {row.at:%Y-%m-%d %H:%M UTC} "
            f"but {expected:%Y-%m-%d %H:%M UTC} was requested"
        )
    return row, index
