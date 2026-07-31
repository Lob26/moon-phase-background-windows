"""Tests for the horizon geometry.

The strongest test here is the cross-check at the bottom: NASA publishes a
"Geographic Region of Eclipse Visibility" for every eclipse, derived
independently of anything in this repo. If our altitude maths says the Moon is
up in a region NASA does not list -- or down in one it does -- one of us is
wrong, and it isn't NASA.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from moonback.moondata import parse_mooninfo, select_hour
from moonback.visibility import (
    HORIZON_MARGIN,
    Observer,
    Visibility,
    altitude_degrees,
    classify,
    describe,
    greenwich_sidereal_degrees,
    julian_date,
)

BOGOTA = Observer("Bogota", 4.71, -74.07)


class TestJulianDate:
    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            # Meeus, Astronomical Algorithms, chapter 7 worked examples.
            pytest.param(datetime(2000, 1, 1, 12), 2451545.0, id="J2000-epoch"),
            pytest.param(datetime(1987, 1, 27), 2446822.5, id="meeus-7b"),
            pytest.param(datetime(1987, 6, 19, 12), 2446966.0, id="meeus-7c"),
            pytest.param(datetime(1988, 1, 27), 2447187.5, id="meeus-7d"),
            pytest.param(datetime(1988, 6, 19, 12), 2447332.0, id="meeus-7e"),
            pytest.param(datetime(1957, 10, 4, 19, 26, 24), 2436116.31, id="sputnik-1"),
        ],
    )
    def test_matches_published_worked_examples(self, moment: datetime, expected: float) -> None:
        assert julian_date(moment) == pytest.approx(expected, abs=1e-2)

    def test_january_and_february_fold_into_the_previous_year(self) -> None:
        # The month <= 2 branch is where hand-rolled JD code usually breaks.
        assert julian_date(datetime(2026, 3, 1)) - julian_date(datetime(2026, 2, 28)) == 1.0
        assert julian_date(datetime(2028, 3, 1)) - julian_date(datetime(2028, 2, 28)) == 2.0

    def test_an_aware_moment_is_converted_to_utc(self) -> None:
        aware = datetime(2000, 1, 1, 7, tzinfo=timezone(timedelta(hours=-5)))

        assert julian_date(aware) == pytest.approx(2451545.0)


class TestSiderealTime:
    def test_matches_the_reference_value_at_j2000(self) -> None:
        assert greenwich_sidereal_degrees(datetime(2000, 1, 1, 12, tzinfo=UTC)) == pytest.approx(
            280.46061837, abs=1e-4
        )

    def test_advances_by_a_sidereal_day(self) -> None:
        first = greenwich_sidereal_degrees(datetime(2026, 3, 3, 0, tzinfo=UTC))
        later = greenwich_sidereal_degrees(datetime(2026, 3, 4, 0, tzinfo=UTC))

        # A solar day is ~360.986 degrees of sidereal rotation, not 360.
        assert (later - first) % 360.0 == pytest.approx(0.9856, abs=1e-3)


class TestAltitude:
    def test_an_object_at_the_zenith(self) -> None:
        # Declination equal to latitude, on the observer's meridian -> overhead.
        moment = datetime(2026, 3, 3, 11, tzinfo=UTC)
        observer = Observer("test", 20.0, 0.0)
        ra_on_meridian = greenwich_sidereal_degrees(moment) / 15.0

        altitude = altitude_degrees(
            observer, moment, right_ascension_hours=ra_on_meridian, declination_degrees=20.0
        )

        assert altitude == pytest.approx(90.0, abs=0.01)

    def test_the_antipode_sees_it_below_the_horizon(self) -> None:
        moment = datetime(2026, 3, 3, 11, tzinfo=UTC)
        ra = greenwich_sidereal_degrees(moment) / 15.0
        here = altitude_degrees(
            Observer("here", 20.0, 0.0), moment, right_ascension_hours=ra, declination_degrees=20.0
        )
        there = altitude_degrees(
            Observer("there", -20.0, 180.0),
            moment,
            right_ascension_hours=ra,
            declination_degrees=20.0,
        )

        assert here == pytest.approx(90.0, abs=0.01)
        assert there == pytest.approx(-90.0, abs=0.01)

    def test_altitude_stays_within_range_across_a_whole_year(self) -> None:
        rows = parse_mooninfo(
            (Path(__file__).resolve().parent.parent / "data" / "mooninfo_2026.txt").read_text(
                encoding="utf-8"
            )
        )

        for row in rows[::211]:
            altitude = altitude_degrees(
                BOGOTA,
                row.at,
                right_ascension_hours=row.right_ascension_hours,
                declination_degrees=row.declination_degrees,
            )
            assert -90.0 <= altitude <= 90.0


class TestObserver:
    @pytest.mark.parametrize(
        ("latitude", "longitude"),
        [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)],
    )
    def test_impossible_coordinates_are_refused(self, latitude: float, longitude: float) -> None:
        with pytest.raises(ValueError, match="must be between"):
            Observer("nowhere", latitude, longitude)

    @pytest.mark.parametrize(
        ("latitude", "longitude"), [(90.0, 180.0), (-90.0, -180.0), (0.0, 0.0)]
    )
    def test_extremes_are_allowed(self, latitude: float, longitude: float) -> None:
        assert Observer("edge", latitude, longitude).latitude == latitude


class TestClassifyAndDescribe:
    @pytest.mark.parametrize(
        ("altitude", "expected"),
        [
            (45.0, Visibility.ABOVE),
            (HORIZON_MARGIN + 0.1, Visibility.ABOVE),
            (HORIZON_MARGIN, Visibility.MARGINAL),
            (0.0, Visibility.MARGINAL),
            (-HORIZON_MARGIN, Visibility.MARGINAL),
            (-HORIZON_MARGIN - 0.1, Visibility.BELOW),
            (-60.0, Visibility.BELOW),
        ],
    )
    def test_the_horizon_band_is_treated_as_uncertain(self, altitude: float, expected: str) -> None:
        # Parallax and refraction are each about half a degree, so a hard
        # altitude > 0 test would state a confident answer we cannot support.
        assert classify(altitude) == expected

    def test_below_the_horizon_gets_no_headline(self) -> None:
        assert describe(BOGOTA, -20.0) is None

    def test_a_marginal_altitude_is_worded_honestly(self) -> None:
        note = describe(BOGOTA, 1.0)

        assert note is not None
        assert "horizon" in note and "VISIBLE" not in note

    def test_a_high_moon_is_called_out(self) -> None:
        assert describe(BOGOTA, 76.0) == "VISIBLE FROM BOGOTA - HIGH OVERHEAD"

    def test_a_modest_altitude_still_gets_the_call_to_action(self) -> None:
        assert describe(BOGOTA, 20.0) == "VISIBLE FROM BOGOTA - LOOK UP"


# NASA, 2026 Mar 03 total lunar eclipse: "e Asia, Australia, Pacific, Americas"
ECLIPSE = datetime(2026, 3, 3, 11, tzinfo=UTC)


@pytest.fixture
def eclipse_moon(real_2026_text: str):
    hour, _ = select_hour(parse_mooninfo(real_2026_text), ECLIPSE)
    return hour


class TestAgainstNasaVisibilityRegions:
    """Cross-check against NASA's published region list, an independent oracle."""

    PLACES = [
        pytest.param(Observer("Tokyo", 35.68, 139.65), True, id="Tokyo-e-Asia"),
        pytest.param(Observer("Sydney", -33.87, 151.21), True, id="Sydney-Australia"),
        pytest.param(Observer("Honolulu", 21.31, -157.86), True, id="Honolulu-Pacific"),
        pytest.param(Observer("Los Angeles", 34.05, -118.24), True, id="LA-Americas"),
        pytest.param(Observer("London", 51.51, -0.13), False, id="London-Europe-excluded"),
        pytest.param(Observer("Cairo", 30.04, 31.24), False, id="Cairo-Africa-excluded"),
        pytest.param(Observer("Lagos", 6.52, 3.38), False, id="Lagos-Africa-excluded"),
    ]

    @pytest.mark.parametrize(("observer", "nasa_lists_it"), PLACES)
    def test_agrees_with_nasa(self, eclipse_moon, observer: Observer, nasa_lists_it: bool) -> None:
        altitude = altitude_degrees(
            observer,
            ECLIPSE,
            right_ascension_hours=eclipse_moon.right_ascension_hours,
            declination_degrees=eclipse_moon.declination_degrees,
        )

        assert (altitude > 0) is nasa_lists_it, (
            f"{observer.name} altitude {altitude:.1f} contradicts NASA's region list"
        )

    def test_bogota_catches_the_partial_phase_but_misses_totality(self, real_2026_text: str):
        # NASA lists the Americas, but the Moon sets over Colombia mid-eclipse:
        # the partial phase is visible and totality is not. Reporting a blanket
        # "visible" here would be wrong, which is the point of computing it.
        rows = parse_mooninfo(real_2026_text)

        def altitude_at(hour_utc: int) -> float:
            row, _ = select_hour(rows, datetime(2026, 3, 3, hour_utc, tzinfo=UTC))
            return altitude_degrees(
                BOGOTA,
                datetime(2026, 3, 3, hour_utc, tzinfo=UTC),
                right_ascension_hours=row.right_ascension_hours,
                declination_degrees=row.declination_degrees,
            )

        assert altitude_at(10) > HORIZON_MARGIN  # partial phase, Moon still up
        assert altitude_at(12) < -HORIZON_MARGIN  # totality, Moon has set
