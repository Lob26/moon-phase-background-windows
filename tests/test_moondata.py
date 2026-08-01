"""Behaviour tests for the phase/age arithmetic.

The interesting failure here is not a crash -- it is a wallpaper that renders
perfectly while showing the wrong day. So these tests assert against the
ephemeris' own timestamps and against independently known lunar events, not
against a restatement of the formula under test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from moonback.moondata import (
    MoonDataError,
    MoonHour,
    frame_filename,
    frame_number,
    hour_index,
    parse_mooninfo,
    select_hour,
)

from .conftest import build_mooninfo, make_hour


class TestParseMooninfo:
    def test_parses_the_real_2026_table(self, real_2026_text: str) -> None:
        rows = parse_mooninfo(real_2026_text)

        assert len(rows) == 8760, "2026 is not a leap year: 365 * 24 hours"
        assert rows[0] == MoonHour(
            at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            illumination_pct=91.40,
            cycle_age_days=11.928,
            distance_km=361045.0,
            right_ascension_hours=4.2348,
            declination_degrees=26.3373,
        )
        assert rows[-1].at == datetime(2026, 12, 31, 23, 0, tzinfo=UTC)

    def test_reads_the_coordinate_columns(self, real_2026_text: str) -> None:
        # RA and Dec are what the horizon maths in visibility.py runs on.
        rows = parse_mooninfo(real_2026_text)

        assert all(0.0 <= row.right_ascension_hours < 24.0 for row in rows)
        assert all(-90.0 <= row.declination_degrees <= 90.0 for row in rows)
        # The Moon's declination swings well past the ecliptic tilt each month.
        assert max(row.declination_degrees for row in rows) > 20.0
        assert min(row.declination_degrees for row in rows) < -20.0

    def test_skips_the_header_row(self) -> None:
        rows = parse_mooninfo(build_mooninfo(datetime(2026, 1, 1, tzinfo=UTC), 3))

        assert len(rows) == 3
        assert rows[0].at == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def test_rows_are_consecutive_hours(self, real_2026_text: str) -> None:
        rows = parse_mooninfo(real_2026_text)

        gaps = {b.at - a.at for a, b in zip(rows[:-1], rows[1:], strict=True)}
        # A gap or duplicate would silently shift every frame after it.
        assert gaps == {timedelta(hours=1)}

    def test_illumination_stays_within_physical_bounds(self, real_2026_text: str) -> None:
        rows = parse_mooninfo(real_2026_text)

        assert all(0.0 <= row.illumination_pct <= 100.0 for row in rows)
        assert all(0.0 <= row.cycle_age_days <= 30.0 for row in rows)

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("", id="empty"),
            pytest.param("   Date       Time    Phase    Age\n", id="header-only"),
            pytest.param("not an ephemeris at all\n", id="garbage"),
            pytest.param("01 Jan 2026 00:00 EST  91.40  11.928\n", id="not-UT"),
            pytest.param("01 Foo 2026 00:00 UT  91.40  11.928\n", id="bad-month"),
        ],
    )
    def test_rejects_tables_it_cannot_read(self, text: str) -> None:
        with pytest.raises(MoonDataError, match="no parsable data rows"):
            parse_mooninfo(text)


class TestHourIndex:
    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            pytest.param(datetime(2026, 1, 1, 0, tzinfo=UTC), 0, id="first-hour-of-year"),
            pytest.param(datetime(2026, 1, 1, 23, tzinfo=UTC), 23, id="last-hour-of-day-one"),
            pytest.param(datetime(2026, 1, 2, 0, tzinfo=UTC), 24, id="second-day-starts-at-24"),
            pytest.param(datetime(2026, 12, 31, 23, tzinfo=UTC), 8759, id="last-hour-common-year"),
            pytest.param(datetime(2028, 12, 31, 23, tzinfo=UTC), 8783, id="last-hour-leap-year"),
            pytest.param(datetime(2028, 3, 1, 0, tzinfo=UTC), 1440, id="leap-day-shifts-march"),
        ],
    )
    def test_indexes_hours_of_the_year_from_zero(self, moment: datetime, expected: int) -> None:
        assert hour_index(moment) == expected

    def test_minutes_and_seconds_do_not_advance_the_hour(self) -> None:
        assert hour_index(datetime(2026, 6, 15, 13, 59, 59, tzinfo=UTC)) == hour_index(
            datetime(2026, 6, 15, 13, 0, 0, tzinfo=UTC)
        )

    def test_converts_other_offsets_to_utc(self) -> None:
        bogota = timezone(timedelta(hours=-5))

        # 2026-01-01 00:00 in Bogota is 05:00 UTC, so hour 5 -- not hour 0.
        assert hour_index(datetime(2026, 1, 1, 0, tzinfo=bogota)) == 5

    def test_offset_can_move_the_moment_into_the_previous_year(self) -> None:
        kolkata = timezone(timedelta(hours=5, minutes=30))
        moment = datetime(2026, 1, 1, 2, 0, tzinfo=kolkata)  # 2025-12-31 20:30 UTC

        assert moment.astimezone(UTC).year == 2025
        assert hour_index(moment) == 8756

    def test_naive_datetimes_are_refused(self) -> None:
        # The original script called datetime.now() and indexed UTC data with it,
        # so every machine outside UTC showed the wrong hour.
        with pytest.raises(MoonDataError, match="timezone-aware"):
            hour_index(datetime(2026, 1, 1, 0))


class TestFrameNumbering:
    @pytest.mark.parametrize(
        ("index", "number", "filename"),
        [
            (0, 1, "moon.0001.tif"),
            (1, 2, "moon.0002.tif"),
            (309, 310, "moon.0310.tif"),
            (8759, 8760, "moon.8760.tif"),
        ],
    )
    def test_frames_are_one_based(self, index: int, number: int, filename: str) -> None:
        # NASA serves moon.0001.tif for the first hour of the year; moon.0000.tif is a 404.
        assert frame_number(index) == number
        assert frame_filename(index) == filename

    def test_negative_index_is_refused(self) -> None:
        with pytest.raises(MoonDataError, match="must not be negative"):
            frame_number(-1)


class TestSelectHour:
    def test_returns_the_row_whose_timestamp_matches(self, real_2026_text: str) -> None:
        rows = parse_mooninfo(real_2026_text)

        row, index = select_hour(rows, datetime(2026, 1, 1, 0, tzinfo=UTC))

        assert index == 0
        assert row.at == datetime(2026, 1, 1, 0, tzinfo=UTC)
        assert row.illumination_pct == pytest.approx(91.40)
        assert row.cycle_age_days == pytest.approx(11.928)

    def test_every_row_is_reachable_from_its_own_timestamp(self, real_2026_text: str) -> None:
        rows = parse_mooninfo(real_2026_text)

        for expected_index in range(0, len(rows), 97):  # prime stride: hits every hour-of-day
            row, index = select_hour(rows, rows[expected_index].at)
            assert index == expected_index
            assert row is rows[expected_index]

    def test_matches_an_independently_known_full_moon(self, real_2026_text: str) -> None:
        # Full moon of 2026-01-03, ~10:03 UTC (independent of this codebase).
        rows = parse_mooninfo(real_2026_text)

        row, _ = select_hour(rows, datetime(2026, 1, 3, 10, tzinfo=UTC))

        assert row.illumination_pct > 99.5
        assert row.cycle_age_days == pytest.approx(14.3, abs=0.5)

    def test_matches_an_independently_known_new_moon(self, real_2026_text: str) -> None:
        # New moon of 2026-01-18, 19:52 UTC.
        rows = parse_mooninfo(real_2026_text)

        row, _ = select_hour(rows, datetime(2026, 1, 18, 20, tzinfo=UTC))

        assert row.illumination_pct < 0.5

    def test_the_old_off_by_one_would_have_been_caught(self, real_2026_text: str) -> None:
        """Regression guard for the bug this rewrite fixed.

        The original computed ``tm_yday * 24 + hour`` -- one full day too far --
        which lands on a real row with plausible values. Only the timestamp
        check distinguishes it.
        """
        rows = parse_mooninfo(real_2026_text)
        moment = datetime(2026, 1, 3, 10, tzinfo=UTC)

        correct, index = select_hour(rows, moment)
        old_index = moment.timetuple().tm_yday * 24 + moment.hour

        assert old_index == index + 24
        assert rows[old_index].at == moment + timedelta(days=1)
        assert rows[old_index].cycle_age_days == pytest.approx(correct.cycle_age_days + 1, abs=0.02)

    def test_a_shifted_table_is_rejected_rather_than_used(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        shifted = parse_mooninfo(build_mooninfo(start + timedelta(hours=1), 48))

        with pytest.raises(MoonDataError, match="was requested"):
            select_hour(shifted, start)

    def test_a_table_for_the_wrong_year_is_rejected(self, real_2025_text: str) -> None:
        rows = parse_mooninfo(real_2025_text)

        with pytest.raises(MoonDataError, match="2026-06-01"):
            select_hour(rows, datetime(2026, 6, 1, 12, tzinfo=UTC))

    def test_a_moment_past_the_end_of_the_table_is_rejected(self) -> None:
        rows = parse_mooninfo(build_mooninfo(datetime(2026, 1, 1, tzinfo=UTC), 10))

        with pytest.raises(MoonDataError, match="ephemeris covers 10 hours"):
            select_hour(rows, datetime(2026, 6, 1, 12, tzinfo=UTC))


class TestLabel:
    def test_reproduces_the_caption_format(self) -> None:
        hour = make_hour(datetime(2026, 1, 1, tzinfo=UTC), 91.40, 11.928)

        assert hour.label == "Phase: 91.40% Days: 11.928"

    def test_pads_to_the_precision_nasa_publishes(self) -> None:
        hour = make_hour(datetime(2026, 1, 1, tzinfo=UTC), 1.5, 1.0)

        assert hour.label == "Phase: 1.50% Days: 1.000"
