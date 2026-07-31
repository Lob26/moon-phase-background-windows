"""Caption placement: corners, and staying clear of the taskbar.

The bug this prevents is mundane and was live: on a 1440x900 desktop with a
96 px taskbar, the old fixed offset put the caption about 88 screen pixels
above the bottom edge -- underneath the taskbar, invisible.
"""

from __future__ import annotations

import pytest

from moonback.config import PROFILES
from moonback.layout import (
    CORNERS,
    Edge,
    Screen,
    Taskbar,
    place,
    taskbar_in_canvas_pixels,
)

STANDARD = PROFILES["standard"]
SCREEN = Screen(width_px=1440, height_px=900)
BOTTOM_TASKBAR = Taskbar(edge=Edge.BOTTOM, thickness_px=96)


def placement(corner: str, **kwargs):
    return place(
        corner,
        canvas_width=STANDARD.canvas_width,
        canvas_height=STANDARD.canvas_height,
        margin=STANDARD.caption_margin,
        leading=85,
        **kwargs,
    )


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
        assert placement(corner).gravity == gravity

    def test_an_unknown_corner_lists_the_valid_ones(self) -> None:
        with pytest.raises(ValueError, match="bottom-right"):
            placement("middle")

    def test_every_advertised_corner_resolves(self) -> None:
        # CORNERS is what config validates against and the installer offers.
        for corner in CORNERS:
            assert placement(corner).gravity

    def test_the_default_reproduces_the_original_placement(self) -> None:
        # gravity east +100+1200 on a 3640-tall canvas is 1820 - 1200 = 620
        # up from the bottom. Existing wallpapers must not visibly move.
        spot = placement("bottom-right")

        assert (spot.gravity, spot.x, spot.caption_y) == ("southeast", 100, 620)

    def test_the_headline_is_always_further_from_the_corner_edge(self) -> None:
        # Gravity measures inward, so "above the caption" is a larger offset in
        # a bottom corner and in a top corner alike.
        for corner in CORNERS:
            spot = placement(corner)
            assert spot.headline_y == spot.caption_y + 85


class TestTaskbarScaling:
    def test_screen_pixels_convert_by_the_width_ratio(self) -> None:
        # Windows "Fill" scales the 3:2 canvas to the screen width and crops
        # the height, so width is the ratio that survives.
        assert taskbar_in_canvas_pixels(BOTTOM_TASKBAR, SCREEN, 5461) == 364

    @pytest.mark.parametrize(
        ("taskbar", "screen"),
        [
            (None, SCREEN),
            (BOTTOM_TASKBAR, None),
            (BOTTOM_TASKBAR, Screen(width_px=0, height_px=900)),
        ],
    )
    def test_unknown_desktops_contribute_nothing(self, taskbar, screen) -> None:
        # Detection is best effort; a failure must degrade to the old behaviour.
        assert taskbar_in_canvas_pixels(taskbar, screen, 5461) == 0


class TestTaskbarAvoidance:
    def test_a_bottom_taskbar_lifts_a_bottom_caption(self) -> None:
        spot = placement("bottom-right", taskbar=BOTTOM_TASKBAR, screen=SCREEN)

        assert spot.caption_y == 620 + 364

    def test_a_bottom_taskbar_leaves_a_top_caption_alone(self) -> None:
        spot = placement("top-right", taskbar=BOTTOM_TASKBAR, screen=SCREEN)

        assert spot.caption_y == 620, "only the corner's own edges can cover it"

    def test_a_side_taskbar_pushes_the_caption_inward(self) -> None:
        left = Taskbar(edge=Edge.LEFT, thickness_px=96)

        assert placement("bottom-left", taskbar=left, screen=SCREEN).x == 100 + 364
        assert placement("bottom-right", taskbar=left, screen=SCREEN).x == 100

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
        spot = placement(corner, taskbar=Taskbar(edge=edge, thickness_px=96), screen=SCREEN)
        baseline = placement(corner)

        shifted = (spot.x, spot.caption_y) != (baseline.x, baseline.caption_y)
        assert shifted is moves

    def test_a_taskbar_never_moves_the_caption_in_two_directions(self) -> None:
        spot = placement("bottom-right", taskbar=BOTTOM_TASKBAR, screen=SCREEN)

        assert spot.x == 100, "a bottom taskbar is not a horizontal obstruction"

    def test_the_taskbar_allowance_widens_a_thin_margin(self) -> None:
        """What this actually buys, measured in screen pixels.

        The fixed offset was not hidden on a 1440x900 desktop -- it cleared a
        96 px taskbar by about 37 px. That is a thin margin that nothing was
        maintaining: a thicker taskbar, a side-docked one, or a taller screen
        aspect eats it. The allowance turns luck into arithmetic.
        """
        scale = SCREEN.width_px / STANDARD.canvas_width
        # "Fill" crops the canvas to the screen aspect, top and bottom equally.
        visible_height = STANDARD.canvas_width * SCREEN.height_px / SCREEN.width_px
        crop = (STANDARD.canvas_height - visible_height) / 2

        def clearance(caption_y: int) -> float:
            return (caption_y - crop) * scale - BOTTOM_TASKBAR.thickness_px

        assert clearance(placement("bottom-right").caption_y) == pytest.approx(37, abs=2)
        assert clearance(
            placement("bottom-right", taskbar=BOTTOM_TASKBAR, screen=SCREEN).caption_y
        ) == pytest.approx(133, abs=2)

    def test_a_thick_taskbar_would_have_covered_the_fixed_offset(self) -> None:
        # The case the allowance genuinely rescues: a taskbar thicker than the
        # margin the old fixed offset happened to leave.
        thick = Taskbar(edge=Edge.BOTTOM, thickness_px=200)
        scale = SCREEN.width_px / STANDARD.canvas_width
        visible = STANDARD.canvas_width * SCREEN.height_px / SCREEN.width_px
        crop = (STANDARD.canvas_height - visible) / 2

        fixed = (placement("bottom-right").caption_y - crop) * scale
        adjusted = (
            placement("bottom-right", taskbar=thick, screen=SCREEN).caption_y - crop
        ) * scale

        assert fixed < thick.thickness_px, "the fixed offset would be behind it"
        assert adjusted > thick.thickness_px
