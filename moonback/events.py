"""Supermoons, micromoons and blue moons: the things a full moon can also be.

All of it comes from columns the ephemeris already has -- illumination for
finding the full moons, distance for judging them -- so this needs no new data
source, no network and no clock. Pure, like moondata and eclipses.

The definitions are folklore dressed as astronomy, so each threshold is named
and sourced rather than left as a number in an expression.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .moondata import MoonHour

#: A full moon nearer than this counts as a supermoon. Fred Espenak's
#: threshold: within 90% of the Moon's closest approach. The popular press
#: uses anything from 356,000 to 370,000 km, so this is a choice, not a fact.
SUPERMOON_MAX_KM = 361_885.0

#: The mirror of the above, near apogee. 2026's two micromoons sit at 406,093
#: and 405,252 km; the year's actual maximum is 406,436.
MICROMOON_MIN_KM = 405_000.0

#: Below this an hour is not a candidate for the monthly peak at all.
FULL_MOON_MIN_ILLUMINATION = 98.0

#: Hours either side of the exact peak that still get the label. A supermoon
#: that showed for the single hour of maximum illumination would be missed by
#: almost everyone; a night either side is what people mean by "tonight".
EVENT_WINDOW = timedelta(hours=12)

#: Half-width of the window used to find a local maximum in illumination.
_PEAK_WINDOW = 12

#: Full moons are ~29.5 days apart; anything closer is the same peak twice.
_MIN_PEAK_SEPARATION = timedelta(days=20)

#: A blue moon is the *second* full moon of its calendar month.
_BLUE_MOON_ORDINAL = 2


@dataclass(frozen=True, slots=True)
class FullMoon:
    """A full moon and whatever else it happens to be."""

    hour: MoonHour
    is_supermoon: bool
    is_micromoon: bool
    is_blue_moon: bool

    @property
    def labels(self) -> tuple[str, ...]:
        """Caption fragments, most striking first."""
        names = []
        if self.is_supermoon:
            names.append("Supermoon")
        if self.is_micromoon:
            names.append("Micromoon")
        if self.is_blue_moon:
            names.append("Blue moon")
        return tuple(names)


def full_moons(rows: tuple[MoonHour, ...]) -> tuple[MoonHour, ...]:
    """The peak hour of each full moon in ``rows``.

    Found as local maxima of illumination rather than by counting from a known
    date, so it needs no epoch and cannot drift. A full moon within twelve
    hours of either end of the table is not detectable -- there is no window to
    compare against -- which at worst skips a label on 1 January.
    """
    peaks: list[MoonHour] = []
    for i in range(_PEAK_WINDOW, len(rows) - _PEAK_WINDOW):
        row = rows[i]
        if row.illumination_pct < FULL_MOON_MIN_ILLUMINATION:
            continue
        window = rows[i - _PEAK_WINDOW : i + _PEAK_WINDOW + 1]
        if row.illumination_pct < max(other.illumination_pct for other in window):
            continue
        if peaks and row.at - peaks[-1].at < _MIN_PEAK_SEPARATION:
            continue
        peaks.append(row)
    return tuple(peaks)


def classify(rows: tuple[MoonHour, ...]) -> tuple[FullMoon, ...]:
    """Label every full moon in the table."""
    peaks = full_moons(rows)

    # A blue moon is the second full moon in one calendar month. The month is
    # UTC here because the ephemeris is; near a month boundary that can differ
    # by a day from the local-calendar tradition the name comes from.
    seen: Counter[tuple[int, int]] = Counter()

    classified: list[FullMoon] = []
    for peak in peaks:
        key = (peak.at.year, peak.at.month)
        seen[key] += 1
        classified.append(
            FullMoon(
                hour=peak,
                is_supermoon=peak.distance_km <= SUPERMOON_MAX_KM,
                is_micromoon=peak.distance_km >= MICROMOON_MIN_KM,
                is_blue_moon=seen[key] == _BLUE_MOON_ORDINAL,
            )
        )
    return tuple(classified)


def describe_at(rows: tuple[MoonHour, ...], moment: datetime) -> tuple[str, ...]:
    """Caption fragments for ``moment``, empty on an ordinary night."""
    when = moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment
    for full in classify(rows):
        if abs(full.hour.at.replace(tzinfo=None) - when) <= EVENT_WINDOW:
            return full.labels
    return ()
