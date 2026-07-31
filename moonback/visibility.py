"""Is the Moon above the horizon from a given place at a given hour?

That question is what turns "there is an eclipse" into "go outside and look".
It needs no new data: NASA's ephemeris already publishes the Moon's right
ascension and declination for every hour, so this is standard spherical
astronomy over numbers the parser already reads.

Pure and dependency-free, like moondata and eclipses.

Two approximations, both deliberate and both far below the resolution this tool
works at:

* The RA/Dec are geocentric. Topocentric parallax shifts the Moon by up to
  about 1 degree, which only matters within a degree of the horizon.
* Atmospheric refraction (about 0.5 degrees at the horizon) is ignored.

Together they mean an eclipse called "just above the horizon" might really be
just below it, or the reverse. HORIZON_MARGIN exists so those cases are
reported as marginal rather than as confident yes/no answers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

#: Altitudes within this many degrees of the horizon are called "marginal":
#: comfortably wider than the parallax and refraction errors above.
HORIZON_MARGIN = 3.0

#: Above this altitude the Moon clears rooftops and trees from almost anywhere.
WELL_PLACED = 45.0

_J2000 = 2451545.0

MAX_LATITUDE = 90.0
MAX_LONGITUDE = 180.0

#: January and February count as months 13 and 14 of the previous year in the
#: Julian Date algorithm, so that leap days fall at the end of the counted year.
_FEBRUARY = 2


@dataclass(frozen=True, slots=True)
class Observer:
    """Somewhere on Earth, in degrees. Longitude is positive east of Greenwich."""

    name: str
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -MAX_LATITUDE <= self.latitude <= MAX_LATITUDE:
            raise ValueError(f"latitude must be between -90 and 90, got {self.latitude}")
        if not -MAX_LONGITUDE <= self.longitude <= MAX_LONGITUDE:
            raise ValueError(f"longitude must be between -180 and 180, got {self.longitude}")


def julian_date(moment: datetime) -> float:
    """Julian Date for a UTC moment, via the standard Fliegel-Van Flandern form."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)

    year, month = moment.year, moment.month
    if month <= _FEBRUARY:
        year -= 1
        month += 12

    a = year // 100
    b = 2 - a + a // 4  # Gregorian correction
    day_fraction = (
        moment.day
        + (moment.hour + moment.minute / 60 + moment.second / 3600) / 24
    )
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day_fraction
        + b
        - 1524.5
    )


def greenwich_sidereal_degrees(moment: datetime) -> float:
    """Greenwich mean sidereal time in degrees, normalised to [0, 360)."""
    days = julian_date(moment) - _J2000
    return (280.46061837 + 360.98564736629 * days) % 360.0


def altitude_degrees(
    observer: Observer,
    moment: datetime,
    *,
    right_ascension_hours: float,
    declination_degrees: float,
) -> float:
    """The Moon's altitude above the horizon, in degrees. Negative means below."""
    hour_angle = math.radians(
        (greenwich_sidereal_degrees(moment) + observer.longitude - right_ascension_hours * 15.0)
        % 360.0
    )
    declination = math.radians(declination_degrees)
    latitude = math.radians(observer.latitude)

    sin_altitude = math.sin(declination) * math.sin(latitude) + math.cos(declination) * math.cos(
        latitude
    ) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_altitude))))


class Visibility:
    """How well an event at a given altitude can be seen."""

    ABOVE = "above"
    MARGINAL = "marginal"
    BELOW = "below"


def classify(altitude: float) -> str:
    if altitude > HORIZON_MARGIN:
        return Visibility.ABOVE
    if altitude < -HORIZON_MARGIN:
        return Visibility.BELOW
    return Visibility.MARGINAL


def describe(observer: Observer, altitude: float) -> str | None:
    """A headline for the wallpaper, or None when the Moon is not up.

    Only the confident cases get the exclamation. "Just above the horizon" is
    the honest wording for the band where our own approximations bite.
    """
    verdict = classify(altitude)
    if verdict == Visibility.BELOW:
        return None
    if verdict == Visibility.MARGINAL:
        return f"On the horizon from {observer.name} - find a clear view"
    if altitude > WELL_PLACED:
        return f"VISIBLE FROM {observer.name.upper()} - HIGH OVERHEAD"
    return f"VISIBLE FROM {observer.name.upper()} - LOOK UP"
