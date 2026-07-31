"""Pure lunar-eclipse logic: parse NASA's catalogue and describe the current hour.

NASA's Dial-A-Moon frames do not render eclipses -- during the total eclipse of
2026-03-03 the published frame is an ordinary full Moon. So without this the
wallpaper would show a bland full disc through totality and say nothing. The
caption is the only signal there is.

Like moondata, nothing here touches the network, the disk or the clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

#: The decade tables publish no duration for penumbral eclipses. They typically
#: run about four hours, so that is the window used to decide whether one is in
#: progress. It is an approximation, and only ever affects an event during which
#: the Moon's brightness changes too little to see.
NOMINAL_PENUMBRAL_DURATION = timedelta(hours=4)

_ROW = re.compile(
    r"""^\s*
    (?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+
    (?P<kind>total|partial|penumbral)\s+
    (?P<umbral>\d+)\s+(?P<totality>\d+)\s*$
    """,
    re.VERBOSE,
)


class EclipseError(Exception):
    """The eclipse catalogue is malformed."""


def _naive_utc(moment: datetime) -> datetime:
    """Normalise to naive UTC, the frame the catalogue's TD timestamps live in.

    Every comparison goes through here, so callers may pass an aware or a naive
    moment and cannot accidentally compare across the two.
    """
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


class EclipseKind(Enum):
    TOTAL = "total"
    PARTIAL = "partial"
    PENUMBRAL = "penumbral"


@dataclass(frozen=True, slots=True)
class Eclipse:
    """One lunar eclipse, centred on the moment of greatest eclipse."""

    greatest: datetime
    kind: EclipseKind
    umbral: timedelta
    """Duration of the partial (umbral) phase; zero for a penumbral eclipse."""

    totality: timedelta
    """Duration of totality; zero unless the eclipse is total."""

    @property
    def duration(self) -> timedelta:
        """How long the Moon looks different enough to be worth mentioning."""
        return self.umbral or NOMINAL_PENUMBRAL_DURATION

    def covers(self, moment: datetime) -> bool:
        return abs(_naive_utc(moment) - self.greatest) <= self.duration / 2

    def in_totality(self, moment: datetime) -> bool:
        return bool(self.totality) and (
            abs(_naive_utc(moment) - self.greatest) <= self.totality / 2
        )

    def describe(self, moment: datetime) -> str:
        """A caption fragment for ``moment``, which must be inside this eclipse."""
        if self.kind is EclipseKind.TOTAL:
            return (
                "Total lunar eclipse (totality)"
                if self.in_totality(moment)
                else "Total lunar eclipse (partial phase)"
            )
        if self.kind is EclipseKind.PARTIAL:
            return "Partial lunar eclipse"
        return "Penumbral lunar eclipse"


def parse_eclipses(text: str) -> tuple[Eclipse, ...]:
    """Parse ``data/lunar_eclipses.txt``. Comment and blank lines are ignored."""
    eclipses: list[Eclipse] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ROW.match(line)
        if match is None:
            raise EclipseError(f"unparsable eclipse row: {line.strip()!r}")
        fields = match.groupdict()
        eclipses.append(
            Eclipse(
                # Naive on purpose: compared against a UTC moment stripped of its
                # tzinfo by eclipse_at, because TD and UT differ by ~70 s here.
                greatest=datetime.fromisoformat(fields["stamp"]),
                kind=EclipseKind(fields["kind"]),
                umbral=timedelta(minutes=int(fields["umbral"])),
                totality=timedelta(minutes=int(fields["totality"])),
            )
        )

    if not eclipses:
        raise EclipseError("eclipse catalogue contained no entries")
    return tuple(eclipses)


def eclipse_at(eclipses: tuple[Eclipse, ...], moment: datetime) -> Eclipse | None:
    """Return the eclipse in progress at ``moment``, if any.

    ``moment`` may be timezone-aware or naive; see :func:`_naive_utc`.
    """
    return next((eclipse for eclipse in eclipses if eclipse.covers(moment)), None)


def describe_at(eclipses: tuple[Eclipse, ...], moment: datetime) -> str | None:
    """The caption fragment for ``moment``, or None when no eclipse is under way."""
    eclipse = eclipse_at(eclipses, moment)
    return eclipse.describe(moment) if eclipse else None
