"""Caption placement: corners, cropping and the taskbar.

Two bugs live here, both of which put the caption a sixth of the way up the
screen instead of in a corner:

* the inset was measured from the canvas edge, but Windows "Fill" crops the
  canvas before you see it, so that edge is off-screen;
* SHAppBarMessage reports physical pixels while GetSystemMetrics reports
  DPI-virtualised ones, making a 96 px taskbar on a 2880 px screen look like
  96 px on a 1440 px one -- twice its true share.

Both are geometry, so both are pinned here in screen pixels: the unit the
person looking at the wallpaper actually cares about.
"""

from __future__ import annotations

import pytest

from moonback.config import PROFILES
from moonback.layout import (
    CORNER_INSET,
    CORNERS,
    HEADLINE_LEADING,
    MAX_DISC_FRACTION,
    Edge,
    Screen,
    Taskbar,
    disc_fraction_of_frame,
    fit_to_screen,
    moon_scale,
    place,
    place_native,
)

STANDARD = PROFILES["standard"]

#: The display this was reported on: 2880x1800 physical, 96 px taskbar.
SCREEN = Screen(width_px=2880, height_px=1800)
BOTTOM_TASKBAR = Taskbar(edge=Edge.BOTTOM, thickness_px=96)


def placement(corner: str, **kwargs):
    return place(
        corner,
        canvas_width=STANDARD.canvas_width,
        canvas_height=STANDARD.canvas_height,
        margin=STANDARD.caption_margin,
        point_size=STANDARD.point_size,
        **kwargs,
    )


def screen_offsets(spot, screen: Screen = SCREEN) -> tuple[float, float]:
    """Distance from the corner's own edges, in physical screen pixels."""
    fit = fit_to_screen(STANDARD.canvas_width, STANDARD.canvas_height, screen)
    return ((spot.x - fit.crop_x) * fit.scale, (spot.caption_y - fit.crop_y) * fit.scale)


class TestFitToScreen:
    def test_a_wider_screen_crops_the_top_and_bottom(self) -> None:
        # 3:2 canvas on a 16:10 screen: scaled to cover the width.
        fit = fit_to_screen(5461, 3640, SCREEN)

        assert fit.scale == pytest.approx(2880 / 5461)
        assert fit.crop_x == 0
        assert fit.crop_y == 113

    def test_a_taller_screen_crops_the_sides(self) -> None:
        # A 4:3 screen is narrower than the 3:2 canvas, so height drives it.
        fit = fit_to_screen(5461, 3640, Screen(width_px=1600, height_px=1200))

        assert fit.scale == pytest.approx(1200 / 3640)
        assert fit.crop_y == 0
        assert fit.crop_x > 0

    def test_an_exactly_matching_aspect_crops_nothing(self) -> None:
        fit = fit_to_screen(3000, 2000, Screen(width_px=1500, height_px=1000))

        assert (fit.crop_x, fit.crop_y) == (0, 0)
        assert fit.scale == pytest.approx(0.5)


class TestCorners:
    @pytest.mark.parametrize(
        ("corner", "gravity"),
        [
            ("bottom-right", "southeast"),
            ("bottom-left", "southwest"),
            ("top-right", "northeast"),
            ("top-left", "northwest"),
        ],
    )
    def test_each_corner_maps_to_its_gravity(self, corner: str, gravity: str) -> None:
        assert placement(corner, screen=SCREEN).gravity == gravity

    def test_an_unknown_corner_lists_the_valid_ones(self) -> None:
        with pytest.raises(ValueError, match="bottom-right"):
            placement("middle")

    def test_every_advertised_corner_resolves(self) -> None:
        for corner in CORNERS:
            assert placement(corner, screen=SCREEN).gravity

    def test_the_headline_sits_further_in_than_the_caption(self) -> None:
        leading = round(STANDARD.point_size * HEADLINE_LEADING)
        for corner in CORNERS:
            spot = placement(corner, screen=SCREEN)
            assert spot.headline_y == spot.caption_y + leading


class TestVisibleInset:
    def test_the_caption_is_inset_from_what_you_can_see(self) -> None:
        # The regression: measured from the canvas edge this was ~270 screen px
        # up, because the bottom 113 canvas rows are cropped away unseen.
        spot = placement("top-right", screen=SCREEN)
        _, from_edge = screen_offsets(spot)

        assert from_edge == pytest.approx(SCREEN.height_px * CORNER_INSET, abs=2)

    def test_the_inset_is_the_same_on_any_display(self) -> None:
        # Same visual result on a 1080p screen as on this 1800p one.
        small = Screen(width_px=1920, height_px=1080)
        spot = placement("top-left", screen=small)
        _, from_edge = screen_offsets(spot, small)

        assert from_edge == pytest.approx(small.height_px * CORNER_INSET, abs=2)

    def test_the_caption_never_lands_in_the_cropped_region(self) -> None:
        for screen in (SCREEN, Screen(1920, 1080), Screen(1600, 1200), Screen(3440, 1440)):
            fit = fit_to_screen(STANDARD.canvas_width, STANDARD.canvas_height, screen)
            for corner in CORNERS:
                spot = placement(corner, screen=screen, taskbar=BOTTOM_TASKBAR)
                assert spot.x > fit.crop_x
                assert spot.caption_y > fit.crop_y

    def test_without_a_screen_it_falls_back_to_the_canvas_margin(self) -> None:
        # Detection is best effort; with no screen there is no way to know what
        # is cropped, so the historical fixed offset is the honest default.
        spot = placement("bottom-right")

        assert (spot.x, spot.caption_y) == STANDARD.caption_margin


class TestTaskbarAvoidance:
    def test_a_bottom_taskbar_lifts_a_bottom_caption_by_its_thickness(self) -> None:
        without = screen_offsets(placement("bottom-right", screen=SCREEN))[1]
        with_bar = screen_offsets(
            placement("bottom-right", screen=SCREEN, taskbar=BOTTOM_TASKBAR)
        )[1]

        assert with_bar - without == pytest.approx(BOTTOM_TASKBAR.thickness_px, abs=2)

    def test_the_caption_clears_the_taskbar(self) -> None:
        spot = placement("bottom-right", screen=SCREEN, taskbar=BOTTOM_TASKBAR)
        _, from_edge = screen_offsets(spot)

        assert from_edge > BOTTOM_TASKBAR.thickness_px

    def test_a_bottom_taskbar_leaves_a_top_caption_alone(self) -> None:
        with_bar = placement("top-right", screen=SCREEN, taskbar=BOTTOM_TASKBAR)
        without = placement("top-right", screen=SCREEN)

        assert with_bar == without

    def test_a_side_taskbar_pushes_the_caption_inward(self) -> None:
        left = Taskbar(edge=Edge.LEFT, thickness_px=96)

        shifted = screen_offsets(placement("bottom-left", screen=SCREEN, taskbar=left))[0]
        plain = screen_offsets(placement("bottom-left", screen=SCREEN))[0]

        assert shifted - plain == pytest.approx(96, abs=2)
        assert placement("bottom-right", screen=SCREEN, taskbar=left) == placement(
            "bottom-right", screen=SCREEN
        )

    @pytest.mark.parametrize(
        ("edge", "corner", "moves"),
        [
            (Edge.BOTTOM, "bottom-right", True),
            (Edge.BOTTOM, "top-left", False),
            (Edge.TOP, "top-left", True),
            (Edge.TOP, "bottom-right", False),
            (Edge.RIGHT, "top-right", True),
            (Edge.RIGHT, "top-left", False),
            (Edge.LEFT, "bottom-left", True),
            (Edge.LEFT, "bottom-right", False),
        ],
    )
    def test_only_the_shared_edge_matters(self, edge: str, corner: str, moves: bool) -> None:
        spot = placement(corner, screen=SCREEN, taskbar=Taskbar(edge=edge, thickness_px=96))

        assert (spot != placement(corner, screen=SCREEN)) is moves

    def test_a_taskbar_never_moves_the_caption_in_two_directions(self) -> None:
        spot = placement("bottom-right", screen=SCREEN, taskbar=BOTTOM_TASKBAR)

        assert spot.x == placement("bottom-right", screen=SCREEN).x


class TestDpiRegression:
    def test_physical_and_virtualised_sizes_must_not_be_mixed(self) -> None:
        """The bug: a 96 px taskbar measured against a half-size screen.

        SHAppBarMessage always reports physical pixels. Pairing that 96 with a
        DPI-virtualised 1440x900 doubles the taskbar's apparent share of the
        screen, inflating the whole offset by about two thirds.
        """
        correct = screen_offsets(
            placement("bottom-right", screen=SCREEN, taskbar=BOTTOM_TASKBAR)
        )[1]

        virtualised = Screen(width_px=1440, height_px=900)
        wrong_spot = placement("bottom-right", screen=virtualised, taskbar=BOTTOM_TASKBAR)
        # Measured against the real screen, which is what the eye sees.
        wrong = screen_offsets(wrong_spot)[1]

        assert wrong > correct * 1.5, "the mismatch inflates the offset by half again"
        assert correct == pytest.approx(96 + SCREEN.height_px * CORNER_INSET, abs=2)


#: The two monitors this feature was built against, measured from rcMonitor.
PRIMARY = Screen(width_px=2880, height_px=1800)
SECONDARY = Screen(width_px=1920, height_px=1080)


class TestNativePlacement:
    """Placing on an image already rendered at the screen's size."""

    def test_offsets_are_plain_screen_pixels(self) -> None:
        spot = place_native(
            "bottom-right", screen=PRIMARY, point_size=26, taskbar=BOTTOM_TASKBAR
        )

        # 2.5% of 1800 = 45 in from the side, and 45 above a 96 px taskbar.
        assert (spot.x, spot.caption_y) == (45, 141)

    def test_a_smaller_monitor_gets_proportionally_smaller_offsets(self) -> None:
        spot = place_native(
            "bottom-right",
            screen=SECONDARY,
            point_size=18,
            taskbar=Taskbar(edge=Edge.BOTTOM, thickness_px=48),
        )

        assert (spot.x, spot.caption_y) == (27, 75)

    @pytest.mark.parametrize(
        ("corner", "gravity"),
        [
            ("bottom-right", "southeast"),
            ("bottom-left", "southwest"),
            ("top-right", "northeast"),
            ("top-left", "northwest"),
        ],
    )
    def test_every_corner_resolves(self, corner: str, gravity: str) -> None:
        assert place_native(corner, screen=PRIMARY, point_size=26).gravity == gravity

    def test_an_unknown_corner_is_refused(self) -> None:
        with pytest.raises(ValueError, match="bottom-right"):
            place_native("middle", screen=PRIMARY, point_size=26)

    @pytest.mark.parametrize(
        ("edge", "corner", "moves"),
        [
            (Edge.BOTTOM, "bottom-right", True),
            (Edge.BOTTOM, "top-left", False),
            (Edge.TOP, "top-left", True),
            (Edge.RIGHT, "top-right", True),
            (Edge.LEFT, "bottom-right", False),
        ],
    )
    def test_only_the_shared_edge_matters(self, edge: str, corner: str, moves: bool) -> None:
        # Same rule as place(); both now share _corner_offsets().
        bar = Taskbar(edge=edge, thickness_px=96)
        shifted = place_native(corner, screen=PRIMARY, point_size=26, taskbar=bar)
        plain = place_native(corner, screen=PRIMARY, point_size=26)

        assert (shifted != plain) is moves

    def test_no_taskbar_leaves_only_the_inset(self) -> None:
        spot = place_native("bottom-right", screen=PRIMARY, point_size=26)

        assert spot.caption_y == round(PRIMARY.height_px * CORNER_INSET)

    def test_the_headline_leads_off_the_point_size(self) -> None:
        spot = place_native("top-left", screen=PRIMARY, point_size=26)

        assert spot.headline_y == spot.caption_y + round(26 * HEADLINE_LEADING)


class TestNativeMatchesFill:
    """The premise of the whole change, pinned.

    Rendering natively must put the caption where the old canvas-plus-Fill path
    put it *on screen*. If these two disagree, switching to native rendering
    would visibly move every caption.
    """

    @pytest.mark.parametrize("corner", CORNERS)
    @pytest.mark.parametrize(
        "screen",
        [PRIMARY, SECONDARY, Screen(3440, 1440), Screen(1600, 1200), Screen(5120, 1440)],
    )
    def test_same_apparent_position(self, corner: str, screen: Screen) -> None:
        bar = Taskbar(edge=Edge.BOTTOM, thickness_px=48)

        old = place(
            corner,
            canvas_width=STANDARD.canvas_width,
            canvas_height=STANDARD.canvas_height,
            margin=STANDARD.caption_margin,
            point_size=STANDARD.point_size,
            taskbar=bar,
            screen=screen,
        )
        old_x, old_y = screen_offsets(old, screen)
        new = place_native(corner, screen=screen, point_size=26, taskbar=bar)

        assert new.x == pytest.approx(old_x, abs=2)
        assert new.caption_y == pytest.approx(old_y, abs=2)


#: Extremes of the Moon's apparent diameter across 2026, from the ephemeris.
APOGEE_ARCSEC, PERIGEE_ARCSEC = 1763.4, 2009.6
FRAME_HEIGHT = 2160

#: Aspect ratios that are fine today and must stay untouched.
CONVENTIONAL = [Screen(1600, 1200), Screen(2880, 1800), Screen(1920, 1080)]
#: Aspect ratios wider than the 3:2 canvas, where the disc outgrows the screen.
WIDE = [Screen(3440, 1440), Screen(5120, 1440), Screen(3840, 1080)]


def scale_for(screen: Screen, diameter: float = 1885.0) -> float:
    return moon_scale(
        canvas_width=STANDARD.canvas_width,
        canvas_height=STANDARD.canvas_height,
        screen=screen,
        frame_height_px=FRAME_HEIGHT,
        diameter_arcsec=diameter,
    )


def disc_share_of_height(screen: Screen, diameter: float = 1885.0) -> float:
    """What fraction of the screen's height the disc ends up filling."""
    fit = fit_to_screen(STANDARD.canvas_width, STANDARD.canvas_height, screen)
    disc = FRAME_HEIGHT * disc_fraction_of_frame(diameter) * fit.scale * scale_for(screen, diameter)
    return disc / screen.height_px


class TestDiscFractionOfFrame:
    @pytest.mark.parametrize(
        ("diameter", "disc_px"),
        [
            # Measured on the rendered samples, centre-row width.
            pytest.param(1770.7, 1827, id="03-midyear-dial-a-moon"),
            pytest.param(1836.4, 1895, id="05-eclipse-visible-dial-a-moon"),
            pytest.param(1872.9, 1938, id="07-totality-telescopic"),
        ],
    )
    def test_matches_the_measured_samples(self, diameter: float, disc_px: int) -> None:
        # Within 1%: the telescopic sample is the loosest, since thresholding a
        # dim red disc picks up a little glow.
        predicted = FRAME_HEIGHT * disc_fraction_of_frame(diameter)

        assert predicted == pytest.approx(disc_px, rel=0.01)

    def test_grows_with_apparent_diameter(self) -> None:
        # 14% across a year -- which is why this is not a hard-coded constant.
        assert disc_fraction_of_frame(PERIGEE_ARCSEC) > disc_fraction_of_frame(APOGEE_ARCSEC)


class TestMoonScale:
    @pytest.mark.parametrize("screen", CONVENTIONAL, ids=lambda s: f"{s.width_px}x{s.height_px}")
    @pytest.mark.parametrize("diameter", [APOGEE_ARCSEC, 1885.0, PERIGEE_ARCSEC])
    def test_conventional_screens_are_never_touched(self, screen: Screen, diameter: float) -> None:
        # Exactly 1.0, not merely close: at 1.0 compose() emits no resize at
        # all, so these screens render byte-identically to before.
        assert scale_for(screen, diameter) == 1.0

    @pytest.mark.parametrize("screen", WIDE, ids=lambda s: f"{s.width_px}x{s.height_px}")
    @pytest.mark.parametrize("diameter", [APOGEE_ARCSEC, 1885.0, PERIGEE_ARCSEC])
    def test_wide_screens_are_capped(self, screen: Screen, diameter: float) -> None:
        assert scale_for(screen, diameter) < 1.0
        assert disc_share_of_height(screen, diameter) == pytest.approx(MAX_DISC_FRACTION, abs=1e-6)

    @pytest.mark.parametrize("screen", CONVENTIONAL + WIDE, ids=lambda s: f"{s.width_px}")
    @pytest.mark.parametrize("diameter", [APOGEE_ARCSEC, PERIGEE_ARCSEC])
    def test_the_moon_is_never_clipped(self, screen: Screen, diameter: float) -> None:
        """The bug this exists for: 32:9 was 118-135% of screen height."""
        assert disc_share_of_height(screen, diameter) <= MAX_DISC_FRACTION + 1e-6

    def test_it_never_enlarges(self) -> None:
        # A tall screen shows the whole canvas and then some; the Moon must not
        # be blown up to meet the cap.
        assert scale_for(Screen(1200, 1600)) == 1.0

    def test_a_supermoon_still_looks_bigger_on_a_normal_screen(self) -> None:
        # Capping must not undercut the Supermoon caption: on 16:9 the disc
        # really is larger at perigee than at apogee.
        small = disc_share_of_height(Screen(1920, 1080), APOGEE_ARCSEC)
        large = disc_share_of_height(Screen(1920, 1080), PERIGEE_ARCSEC)

        assert large > small * 1.1

    def test_a_bigger_moon_needs_more_shrinking(self) -> None:
        wide = Screen(5120, 1440)

        assert scale_for(wide, PERIGEE_ARCSEC) < scale_for(wide, APOGEE_ARCSEC)

    def test_a_taller_frame_is_scaled_down_further(self) -> None:
        # The 'large' profile's frames are 3240 tall, and eclipse frames are
        # always 2160, so the incoming height genuinely varies.
        wide = Screen(5120, 1440)
        common = dict(
            canvas_width=STANDARD.canvas_width,
            canvas_height=STANDARD.canvas_height,
            screen=wide,
            diameter_arcsec=1885.0,
        )

        assert moon_scale(frame_height_px=3240, **common) < moon_scale(
            frame_height_px=2160, **common
        )
