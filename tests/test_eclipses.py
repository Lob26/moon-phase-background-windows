"""Behaviour tests for eclipse annotation.

The failure mode mirrors the phase math: not a crash, but a wallpaper that
stays silent through a total lunar eclipse, or announces one on an ordinary
night. So these assert against real, independently known eclipses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from moonback.eclipses import (
    Eclipse,
    EclipseError,
    EclipseKind,
    describe_at,
    eclipse_at,
    parse_eclipses,
)
from moonback.moondata import format_caption

from .conftest import make_hour

CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "data" / "lunar_eclipses.txt"


@pytest.fixture(scope="session")
def catalogue() -> tuple[Eclipse, ...]:
    return parse_eclipses(CATALOGUE_PATH.read_text(encoding="utf-8"))


class TestParseEclipses:
    def test_reads_the_shipped_catalogue(self, catalogue: tuple[Eclipse, ...]) -> None:
        assert len(catalogue) >= 40
        assert all(e.greatest.year >= 2021 for e in catalogue)

    def test_entries_are_chronological(self, catalogue: tuple[Eclipse, ...]) -> None:
        stamps = [e.greatest for e in catalogue]
        assert stamps == sorted(stamps)

    def test_reads_the_2026_total_eclipse(self, catalogue: tuple[Eclipse, ...]) -> None:
        # NASA: 2026 Mar 03, greatest 11:34:52 TD, total, 03h27m umbral / 00h58m total.
        match = next(e for e in catalogue if e.greatest.date() == datetime(2026, 3, 3).date())

        assert match.kind is EclipseKind.TOTAL
        assert match.greatest == datetime(2026, 3, 3, 11, 34, 52)
        assert match.umbral == timedelta(minutes=207)
        assert match.totality == timedelta(minutes=58)

    def test_penumbral_entries_carry_no_umbral_phase(self, catalogue: tuple[Eclipse, ...]) -> None:
        penumbral = [e for e in catalogue if e.kind is EclipseKind.PENUMBRAL]

        assert penumbral, "the catalogue should contain penumbral eclipses"
        assert all(e.umbral == timedelta() and e.totality == timedelta() for e in penumbral)

    def test_only_total_eclipses_have_totality(self, catalogue: tuple[Eclipse, ...]) -> None:
        for eclipse in catalogue:
            has_totality = eclipse.totality > timedelta()
            assert has_totality == (eclipse.kind is EclipseKind.TOTAL)

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        parsed = parse_eclipses(
            "# a comment\n\n2026-03-03T11:34:52   total   207   58\n   \n"
        )

        assert len(parsed) == 1

    def test_a_malformed_row_is_refused_rather_than_skipped(self) -> None:
        # Silently dropping a row would mean silently missing an eclipse.
        with pytest.raises(EclipseError, match="unparsable eclipse row"):
            parse_eclipses("2026-03-03T11:34:52   total   207\n")

    def test_an_unknown_type_is_refused(self) -> None:
        with pytest.raises(EclipseError, match="unparsable eclipse row"):
            parse_eclipses("2026-03-03T11:34:52   annular   207   58\n")

    def test_an_empty_catalogue_is_an_error(self) -> None:
        with pytest.raises(EclipseError, match="no entries"):
            parse_eclipses("# only comments\n")


class TestEclipseAt:
    def test_totality_of_the_2026_eclipse_is_announced(
        self, catalogue: tuple[Eclipse, ...]
    ) -> None:
        # Greatest at 11:34:52; totality is 58m, so it runs 11:05-12:03 and
        # 12:00 is the only whole hour inside it.
        assert describe_at(catalogue, datetime(2026, 3, 3, 12, tzinfo=UTC)) == (
            "Total lunar eclipse (totality)"
        )

    @pytest.mark.parametrize("hour", [10, 11, 13])
    def test_the_partial_phase_is_distinguished_from_totality(
        self, catalogue: tuple[Eclipse, ...], hour: int
    ) -> None:
        # Inside the 3h27m umbral phase but outside the 58m totality -- including
        # 11:00, which is nearer greatest than totality is long on either side.
        assert describe_at(catalogue, datetime(2026, 3, 3, hour, tzinfo=UTC)) == (
            "Total lunar eclipse (partial phase)"
        )

    def test_an_ordinary_hour_gets_no_note(self, catalogue: tuple[Eclipse, ...]) -> None:
        assert describe_at(catalogue, datetime(2026, 3, 3, 0, tzinfo=UTC)) is None
        assert describe_at(catalogue, datetime(2026, 7, 31, 22, tzinfo=UTC)) is None

    def test_a_partial_eclipse_is_named_as_such(self, catalogue: tuple[Eclipse, ...]) -> None:
        # NASA: 2026 Aug 28, greatest 04:14 TD, partial, 03h18m.
        assert describe_at(catalogue, datetime(2026, 8, 28, 4, tzinfo=UTC)) == (
            "Partial lunar eclipse"
        )

    def test_a_penumbral_eclipse_is_named_as_such(self, catalogue: tuple[Eclipse, ...]) -> None:
        # NASA: 2027 Feb 20, greatest 23:14 TD, penumbral.
        assert describe_at(catalogue, datetime(2027, 2, 20, 23, tzinfo=UTC)) == (
            "Penumbral lunar eclipse"
        )

    def test_the_window_closes_after_the_umbral_phase(
        self, catalogue: tuple[Eclipse, ...]
    ) -> None:
        # 207 minutes centred on 11:34 ends at ~13:18, so 14:00 is clear.
        assert describe_at(catalogue, datetime(2026, 3, 3, 13, tzinfo=UTC)) is not None
        assert describe_at(catalogue, datetime(2026, 3, 3, 14, tzinfo=UTC)) is None

    def test_a_local_timezone_is_converted_before_comparison(
        self, catalogue: tuple[Eclipse, ...]
    ) -> None:
        bogota = timezone(timedelta(hours=-5))
        local = datetime(2026, 3, 3, 6, tzinfo=bogota)  # 11:00 UTC

        assert local.astimezone(UTC).hour == 11
        assert eclipse_at(catalogue, local) is not None

    def test_a_naive_moment_is_treated_as_utc(self, catalogue: tuple[Eclipse, ...]) -> None:
        assert eclipse_at(catalogue, datetime(2026, 3, 3, 11)) is not None

    def test_at_most_one_eclipse_matches_any_hour(self, catalogue: tuple[Eclipse, ...]) -> None:
        # Eclipse windows are hours long and separated by months, so an
        # overlap would mean a corrupt catalogue.
        for eclipse in catalogue:
            matches = [e for e in catalogue if e.covers(eclipse.greatest)]
            assert matches == [eclipse]

    def test_no_ordinary_day_of_2026_is_flagged(self, catalogue: tuple[Eclipse, ...]) -> None:
        eclipse_days = {datetime(2026, 3, 3).date(), datetime(2026, 8, 28).date()}
        moment = datetime(2026, 1, 1, tzinfo=UTC)
        flagged = set()

        while moment.year == 2026:
            if describe_at(catalogue, moment):
                flagged.add(moment.date())
            moment += timedelta(hours=1)

        assert flagged == eclipse_days


class TestFormatCaption:
    def test_an_ordinary_night_reads_exactly_as_before(self) -> None:
        hour = make_hour(datetime(2026, 1, 1, tzinfo=UTC), 91.40, 11.928)

        assert format_caption(hour) == "Phase: 91.40% Days: 11.928"
        assert format_caption(hour, None) == "Phase: 91.40% Days: 11.928"

    def test_an_eclipse_is_appended(self) -> None:
        hour = make_hour(datetime(2026, 3, 3, 11, tzinfo=UTC), 100.0, 14.9)

        assert format_caption(hour, "Total lunar eclipse (totality)") == (
            "Phase: 100.00% Days: 14.900 - Total lunar eclipse (totality)"
        )
