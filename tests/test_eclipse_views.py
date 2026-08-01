"""Mapping an eclipse hour onto NASA's telescopic render.

The bug worth preventing is a wrong *frame*, not a crash: pick the wrong index
and you get a real, plausible picture of the Moon at the wrong point in the
eclipse. So the cadence is derived and then checked against the eclipse the
sequence belongs to.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from moonback.config import svs_collection_url
from moonback.eclipse_views import (
    EclipseView,
    EclipseViewError,
    parse_eclipse_views,
    view_at,
)
from moonback.eclipses import parse_eclipses

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def views() -> tuple[EclipseView, ...]:
    return parse_eclipse_views((REPO / "data" / "eclipse_views.txt").read_text(encoding="utf-8"))


class TestParsing:
    def test_reads_the_shipped_table(self, views: tuple[EclipseView, ...]) -> None:
        assert {v.svs_id for v in views} == {5472, 5605}

    def test_reads_the_2026_sequence(self, views: tuple[EclipseView, ...]) -> None:
        view = next(v for v in views if v.svs_id == 5605)

        assert view.date == date(2026, 3, 3)
        assert view.first_frame == datetime(2026, 3, 3, 8, 6, 0)
        assert view.last_frame == datetime(2026, 3, 3, 15, 38, 50)
        assert view.frames == 2718

    @pytest.mark.parametrize(
        "row",
        [
            pytest.param("2026-03-03 5605 2026-03-03T08:06:00 2718\n", id="missing-column"),
            pytest.param("not-a-date 5605 x y 2718\n", id="bad-date"),
        ],
    )
    def test_a_malformed_row_is_refused(self, row: str) -> None:
        # Skipping a row silently would mean silently losing eclipse imagery.
        with pytest.raises(EclipseViewError, match="unparsable"):
            parse_eclipse_views(row)

    def test_a_single_frame_sequence_is_refused(self) -> None:
        # Cadence divides by frames - 1.
        with pytest.raises(EclipseViewError, match="at least 2 frames"):
            parse_eclipse_views(
                "2026-03-03 5605 2026-03-03T08:06:00 2026-03-03T15:38:50 1\n"
            )

    def test_a_backwards_range_is_refused(self) -> None:
        with pytest.raises(EclipseViewError, match="ends before it starts"):
            parse_eclipse_views(
                "2026-03-03 5605 2026-03-03T15:38:50 2026-03-03T08:06:00 2718\n"
            )

    def test_comments_and_blanks_are_ignored(self) -> None:
        assert parse_eclipse_views("# note\n\n") == ()


class TestCadence:
    @pytest.mark.parametrize(
        ("svs_id", "expected"),
        [(5605, 10.000), (5472, 7.723)],
    )
    def test_cadence_is_derived_not_assumed(
        self, views: tuple[EclipseView, ...], svs_id: int, expected: float
    ) -> None:
        # Verified against NASA: frame 1477 of SVS 5472 is mid-totality at
        # 07:00 UTC, which a hard-coded 10 s cadence gets wrong by a whole phase.
        view = next(v for v in views if v.svs_id == svs_id)

        assert view.cadence_seconds == pytest.approx(expected, abs=0.001)

    def test_the_two_sequences_really_do_differ(self, views: tuple[EclipseView, ...]) -> None:
        cadences = {round(v.cadence_seconds, 3) for v in views}

        assert len(cadences) > 1, "if these ever match, the derivation is still the safe choice"


class TestFrameNumbering:
    def test_the_first_and_last_instants_map_to_the_end_frames(
        self, views: tuple[EclipseView, ...]
    ) -> None:
        for view in views:
            assert view.frame_number(view.first_frame) == 1
            assert view.frame_number(view.last_frame) == view.frames

    def test_frames_are_zero_padded_to_four_digits(self, views: tuple[EclipseView, ...]) -> None:
        view = next(v for v in views if v.svs_id == 5605)

        assert view.frame_filename(view.first_frame) == "moon.0001.tif"

    def test_the_known_2026_hours_map_to_the_frames_that_were_downloaded(
        self, views: tuple[EclipseView, ...]
    ) -> None:
        # These exact frame numbers were fetched from NASA and eyeballed:
        # 325 is the shadow just touching, 1405 is deep totality.
        view = next(v for v in views if v.svs_id == 5605)

        assert view.frame_number(datetime(2026, 3, 3, 9, tzinfo=UTC)) == 325
        assert view.frame_number(datetime(2026, 3, 3, 12, tzinfo=UTC)) == 1405

    def test_the_known_2025_totality_frame(self, views: tuple[EclipseView, ...]) -> None:
        view = next(v for v in views if v.svs_id == 5472)

        assert view.frame_number(datetime(2025, 3, 14, 7, tzinfo=UTC)) == 1477

    def test_out_of_range_moments_clamp_rather_than_overflow(
        self, views: tuple[EclipseView, ...]
    ) -> None:
        # covers() gates this in practice, but an off-by-one must never index
        # past the sequence and 404 against NASA.
        view = next(v for v in views if v.svs_id == 5605)

        assert view.frame_number(view.first_frame - timedelta(hours=5)) == 1
        assert view.frame_number(view.last_frame + timedelta(hours=5)) == view.frames

    def test_local_time_is_converted_before_indexing(
        self, views: tuple[EclipseView, ...]
    ) -> None:
        view = next(v for v in views if v.svs_id == 5605)
        bogota = timezone(timedelta(hours=-5))

        assert view.frame_number(datetime(2026, 3, 3, 7, tzinfo=bogota)) == 1405


class TestViewAt:
    def test_finds_the_sequence_covering_an_instant(self, views: tuple[EclipseView, ...]) -> None:
        assert view_at(views, datetime(2026, 3, 3, 12, tzinfo=UTC)).svs_id == 5605

    @pytest.mark.parametrize(
        "moment",
        [
            pytest.param(datetime(2026, 3, 3, 7, tzinfo=UTC), id="before-the-sequence"),
            pytest.param(datetime(2026, 3, 3, 16, tzinfo=UTC), id="after-the-sequence"),
            pytest.param(datetime(2026, 8, 28, 5, tzinfo=UTC), id="eclipse-nasa-did-not-render"),
            pytest.param(datetime(2026, 7, 31, 22, tzinfo=UTC), id="ordinary-night"),
        ],
    )
    def test_returns_none_when_nothing_covers_it(
        self, views: tuple[EclipseView, ...], moment: datetime
    ) -> None:
        # Most eclipses have no sequence; the caller must fall back quietly.
        assert view_at(views, moment) is None

    def test_sequences_do_not_overlap(self, views: tuple[EclipseView, ...]) -> None:
        for view in views:
            matches = [v for v in views if v.covers(view.first_frame)]
            assert matches == [view]


class TestAgreesWithTheEclipseCatalogue:
    """Every sequence must actually cover the eclipse it claims to be for."""

    def test_each_view_spans_its_eclipse(self, views: tuple[EclipseView, ...]) -> None:
        catalogue = (REPO / "data" / "lunar_eclipses.txt").read_text(encoding="utf-8")
        eclipses = parse_eclipses(catalogue)

        for view in views:
            eclipse = next((e for e in eclipses if e.greatest.date() == view.date), None)
            assert eclipse is not None, f"{view.date} is not in lunar_eclipses.txt"
            assert view.covers(eclipse.greatest), (
                f"SVS {view.svs_id} does not cover greatest eclipse at {eclipse.greatest}"
            )

    def test_greatest_eclipse_lands_near_the_middle_of_the_sequence(
        self, views: tuple[EclipseView, ...]
    ) -> None:
        # NASA centres these on the eclipse. A sequence whose midpoint is far
        # from greatest eclipse means the times were transcribed wrong.
        catalogue = (REPO / "data" / "lunar_eclipses.txt").read_text(encoding="utf-8")
        eclipses = parse_eclipses(catalogue)

        for view in views:
            eclipse = next(e for e in eclipses if e.greatest.date() == view.date)
            midpoint = view.first_frame + (view.last_frame - view.first_frame) / 2
            assert abs((midpoint - eclipse.greatest).total_seconds()) < 20 * 60


class TestFrameUrls:
    @pytest.mark.parametrize(
        ("svs_id", "expected"),
        [
            (5605, "https://svs.gsfc.nasa.gov/vis/a000000/a005600/a005605"),
            (5472, "https://svs.gsfc.nasa.gov/vis/a000000/a005400/a005472"),
        ],
    )
    def test_collection_urls_bucket_by_hundreds(self, svs_id: int, expected: str) -> None:
        assert svs_collection_url(svs_id) == expected
