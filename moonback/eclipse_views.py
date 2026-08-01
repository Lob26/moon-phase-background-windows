"""Mapping an eclipse hour onto NASA's dedicated telescopic render.

The Dial-A-Moon sequence models phase and libration, not Earth's shadow, so it
shows an ordinary grey Moon through totality. For major eclipses the SVS
publishes a separate "Telescopic View" sequence that does show the eclipse --
real NASA imagery, not a synthesis. When one exists for the eclipse in
progress, the frame comes from there instead.

Pure, like moondata and eclipses: no network, no disk, no clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

_ROW = re.compile(
    r"""^\s*
    (?P<date>\d{4}-\d{2}-\d{2})\s+
    (?P<svs_id>\d{3,6})\s+
    (?P<first>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+
    (?P<last>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+
    (?P<frames>\d+)\s*$
    """,
    re.VERBOSE,
)


#: Cadence divides by (frames - 1), so a sequence needs at least two frames.
MIN_FRAMES = 2


class EclipseViewError(Exception):
    """The eclipse-view table is malformed."""


@dataclass(frozen=True, slots=True)
class EclipseView:
    """One SVS telescopic sequence, addressable by UTC instant."""

    date: date
    svs_id: int
    first_frame: datetime
    last_frame: datetime
    frames: int

    @property
    def cadence_seconds(self) -> float:
        """Seconds between frames, derived rather than assumed.

        It is 10.000 s for the 2026 sequence and 7.723 s for the 2025 one.
        Assuming a round number puts the 2025 eclipse a full phase out.
        """
        return (self.last_frame - self.first_frame).total_seconds() / (self.frames - 1)

    def covers(self, moment: datetime) -> bool:
        return self.first_frame <= _naive_utc(moment) <= self.last_frame

    def frame_number(self, moment: datetime) -> int:
        """The 1-based frame nearest ``moment``, clamped to the sequence."""
        offset = (_naive_utc(moment) - self.first_frame).total_seconds()
        nearest = round(offset / self.cadence_seconds) + 1
        return max(1, min(self.frames, nearest))

    def frame_filename(self, moment: datetime) -> str:
        return f"moon.{self.frame_number(moment):04d}.tif"


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def parse_eclipse_views(text: str) -> tuple[EclipseView, ...]:
    """Parse ``data/eclipse_views.txt``. Comments and blank lines are ignored."""
    views: list[EclipseView] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ROW.match(line)
        if match is None:
            raise EclipseViewError(f"unparsable eclipse-view row: {line.strip()!r}")

        fields = match.groupdict()
        frames = int(fields["frames"])
        if frames < MIN_FRAMES:
            raise EclipseViewError(
                f"an eclipse view needs at least {MIN_FRAMES} frames, got {frames}"
            )

        first = datetime.fromisoformat(fields["first"])
        last = datetime.fromisoformat(fields["last"])
        if last <= first:
            raise EclipseViewError(f"eclipse view {fields['svs_id']} ends before it starts")

        views.append(
            EclipseView(
                date=date.fromisoformat(fields["date"]),
                svs_id=int(fields["svs_id"]),
                first_frame=first,
                last_frame=last,
                frames=frames,
            )
        )
    return tuple(views)


def view_at(views: tuple[EclipseView, ...], moment: datetime) -> EclipseView | None:
    """The telescopic sequence covering ``moment``, if NASA published one."""
    return next((view for view in views if view.covers(moment)), None)
