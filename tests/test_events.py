"""Supermoons, micromoons and blue moons.

These are folklore with numeric thresholds bolted on, so the tests pin the
thresholds *and* the real 2026 answers. The failure mode is a label that is
merely plausible -- "Supermoon" on an ordinary full moon reads fine and is
still wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from moonback.events import (
    EVENT_WINDOW,
    MICROMOON_MIN_KM,
    SUPERMOON_MAX_KM,
    classify,
    describe_at,
    full_moons,
)
from moonback.moondata import format_caption, parse_mooninfo

from .conftest import make_hour

#: Independently checkable: the Moon's mean distance is ~384,400 km, perigee
#: ~356,500 and apogee ~406,700, so the thresholds must sit inside that range.
PERIGEE_KM, APOGEE_KM = 356_500, 406_700


@pytest.fixture(scope="session")
def rows_2026(real_2026_text: str):
    return parse_mooninfo(real_2026_text)


class TestThresholds:
    def test_the_thresholds_lie_within_the_real_orbit(self) -> None:
        assert PERIGEE_KM < SUPERMOON_MAX_KM < 384_400
        assert 384_400 < MICROMOON_MIN_KM < APOGEE_KM

    def test_a_moon_cannot_be_both(self) -> None:
        assert SUPERMOON_MAX_KM < MICROMOON_MIN_KM


class TestFullMoons:
    def test_finds_every_full_moon_of_2026(self, rows_2026) -> None:
        # 2026 has 13: twelve months plus a second one in May.
        peaks = full_moons(rows_2026)

        assert len(peaks) == 13
        assert all(peak.illumination_pct > 99.5 for peak in peaks)

    def test_peaks_are_about_a_synodic_month_apart(self, rows_2026) -> None:
        peaks = full_moons(rows_2026)
        gaps = [
            (b.at - a.at).total_seconds() / 86400
            for a, b in zip(peaks[:-1], peaks[1:], strict=True)
        ]

        # The synodic month is 29.53 days; the real spread is a few hours.
        assert all(28.5 < gap < 30.5 for gap in gaps), gaps

    def test_each_peak_is_the_brightest_hour_around_it(self, rows_2026) -> None:
        rows = rows_2026
        by_time = {row.at: i for i, row in enumerate(rows)}

        for peak in full_moons(rows):
            i = by_time[peak.at]
            neighbours = rows[max(0, i - 12) : i + 13]
            assert peak.illumination_pct == max(n.illumination_pct for n in neighbours)

    def test_a_flat_table_yields_nothing(self) -> None:
        # A table that never gets bright has no full moons, rather than
        # nominating whichever hour happens to be highest.
        flat = tuple(
            make_hour(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=n), 40.0)
            for n in range(200)
        )

        assert full_moons(flat) == ()


class TestClassification2026:
    """Pinned against the real table -- see the survey in the commit message."""

    def test_the_two_supermoons(self, rows_2026) -> None:
        supers = [f.hour.at.date() for f in classify(rows_2026) if f.is_supermoon]

        assert [str(d) for d in supers] == ["2026-11-24", "2026-12-24"]

    def test_the_two_micromoons(self, rows_2026) -> None:
        micros = [f.hour.at.date() for f in classify(rows_2026) if f.is_micromoon]

        assert [str(d) for d in micros] == ["2026-05-31", "2026-06-30"]

    def test_the_single_blue_moon(self, rows_2026) -> None:
        # May 2026 holds full moons on the 1st and the 31st; the second is blue.
        blues = [f.hour.at.date() for f in classify(rows_2026) if f.is_blue_moon]

        assert [str(d) for d in blues] == ["2026-05-31"]

    def test_the_first_full_moon_of_a_double_month_is_not_blue(self, rows_2026) -> None:
        may_first = next(
            f for f in classify(rows_2026) if f.hour.at.date().isoformat() == "2026-05-01"
        )

        assert not may_first.is_blue_moon

    def test_a_moon_can_be_two_things_at_once(self, rows_2026) -> None:
        # 2026-05-31 is both the month's second full moon and near apogee.
        may_last = next(
            f for f in classify(rows_2026) if f.hour.at.date().isoformat() == "2026-05-31"
        )

        assert may_last.labels == ("Micromoon", "Blue moon")

    def test_most_full_moons_are_unremarkable(self, rows_2026) -> None:
        # 13 full moons, 4 of them labelled -- May 31 carries two labels but is
        # still one moon. A label on every full moon would mean nothing.
        plain = [f for f in classify(rows_2026) if not f.labels]

        assert len(plain) == 9


class TestDescribeAt:
    def test_labels_the_hours_around_the_peak(self, rows_2026) -> None:
        # 2026-12-24 02:00 UTC is a supermoon; the evening either side counts.
        for hour in (14, 2, 14):
            moment = datetime(2026, 12, 23 if hour == 14 else 24, hour, tzinfo=UTC)
            assert describe_at(rows_2026, moment) == ("Supermoon",)

    def test_stops_outside_the_window(self, rows_2026) -> None:
        peak = datetime(2026, 12, 24, 2, tzinfo=UTC)

        assert describe_at(rows_2026, peak + EVENT_WINDOW - timedelta(hours=1))
        assert describe_at(rows_2026, peak + EVENT_WINDOW + timedelta(hours=2)) == ()

    def test_an_ordinary_night_gets_nothing(self, rows_2026) -> None:
        assert describe_at(rows_2026, datetime(2026, 7, 31, 22, tzinfo=UTC)) == ()

    def test_a_plain_full_moon_gets_nothing(self, rows_2026) -> None:
        # 2026-03-03 is a full moon and a total eclipse, but an ordinary distance.
        assert describe_at(rows_2026, datetime(2026, 3, 3, 11, tzinfo=UTC)) == ()

    def test_local_time_is_converted(self, rows_2026) -> None:
        bogota = timezone(timedelta(hours=-5))
        local = datetime(2026, 12, 23, 21, tzinfo=bogota)  # 2026-12-24 02:00 UTC

        assert describe_at(rows_2026, local) == ("Supermoon",)


class TestCaption:
    def test_notes_are_joined_in_order(self) -> None:
        hour = make_hour(datetime(2026, 5, 31, tzinfo=UTC), 99.81, 15.0)

        assert format_caption(hour, "Micromoon", "Blue moon") == (
            "Phase: 99.81% Days: 15.000 - Micromoon - Blue moon"
        )

    def test_empty_notes_are_dropped(self) -> None:
        hour = make_hour(datetime(2026, 1, 1, tzinfo=UTC), 91.40, 11.928)

        assert format_caption(hour, None, "", None) == "Phase: 91.40% Days: 11.928"

    def test_an_eclipse_and_an_event_can_share_a_caption(self) -> None:
        hour = make_hour(datetime(2026, 3, 3, tzinfo=UTC), 100.0, 14.0)

        assert format_caption(hour, "Total lunar eclipse (totality)", "Supermoon") == (
            "Phase: 100.00% Days: 14.000 - Total lunar eclipse (totality) - Supermoon"
        )
