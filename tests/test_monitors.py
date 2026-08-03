"""Monitor geometry and the join to Windows' wallpaper ids.

Everything here is pure: `Rect`s and tuples in, `Display`s out. The Win32 half
of `monitors.py` is not exercised -- it has no logic worth testing, and the
suite runs on ubuntu in CI.

The numbers are the real ones from the desktop this was built against: a
2880x1800 primary at 192 DPI with a 96 px taskbar, and a 1920x1080 secondary at
96 DPI with a 48 px one.
"""

from __future__ import annotations

import pytest

from moonback.layout import Edge
from moonback.monitors import (
    Display,
    Monitor,
    Rect,
    join_by_rect,
    screen_of,
    taskbar_of,
)

PRIMARY_BOUNDS = Rect(0, 0, 2880, 1800)
PRIMARY_WORK = Rect(0, 0, 2880, 1704)
SECOND_BOUNDS = Rect(2880, 0, 4800, 1080)
SECOND_WORK = Rect(2880, 0, 4800, 1032)

PRIMARY = Monitor(bounds=PRIMARY_BOUNDS, work=PRIMARY_WORK, primary=True)
SECOND = Monitor(bounds=SECOND_BOUNDS, work=SECOND_WORK, primary=False)

ENUMERATED = ((PRIMARY, r"\\.\DISPLAY1"), (SECOND, r"\\.\DISPLAY5"))
COM_RECTS = (("id-primary", PRIMARY_BOUNDS), ("id-second", SECOND_BOUNDS))


def monitor(bounds: Rect, work: Rect | None = None, *, primary: bool = False) -> Monitor:
    return Monitor(bounds=bounds, work=work if work is not None else bounds, primary=primary)


class TestRect:
    def test_sizes_come_from_the_edges(self) -> None:
        assert (PRIMARY_BOUNDS.width, PRIMARY_BOUNDS.height) == (2880, 1800)

    def test_a_negative_origin_still_measures_correctly(self) -> None:
        # A monitor placed left of the primary starts at a negative x. Any
        # `left >= 0` assumption would silently break this arrangement.
        left_of_primary = Rect(-1920, -120, 0, 960)

        assert (left_of_primary.width, left_of_primary.height) == (1920, 1080)


class TestScreenOf:
    def test_uses_the_full_bounds_not_the_work_area(self) -> None:
        # The image covers the whole monitor; the taskbar sits on top of it.
        assert screen_of(PRIMARY).height_px == 1800

    def test_a_negative_origin_monitor(self) -> None:
        screen = screen_of(monitor(Rect(-1920, 0, 0, 1080)))

        assert (screen.width_px, screen.height_px) == (1920, 1080)


class TestTaskbarOf:
    def test_the_real_primary(self) -> None:
        bar = taskbar_of(PRIMARY)

        assert bar is not None
        assert (bar.edge, bar.thickness_px) == (Edge.BOTTOM, 96)

    def test_the_real_secondary_has_its_own_thinner_bar(self) -> None:
        # The whole point: 48 px here, 96 px on the primary. SHAppBarMessage
        # reports only the primary's, so the old code used 96 for both.
        bar = taskbar_of(SECOND)

        assert bar is not None
        assert (bar.edge, bar.thickness_px) == (Edge.BOTTOM, 48)

    @pytest.mark.parametrize(
        ("work", "edge", "thickness"),
        [
            (Rect(0, 0, 2880, 1704), Edge.BOTTOM, 96),
            (Rect(0, 96, 2880, 1800), Edge.TOP, 96),
            (Rect(120, 0, 2880, 1800), Edge.LEFT, 120),
            (Rect(0, 0, 2760, 1800), Edge.RIGHT, 120),
        ],
    )
    def test_every_docked_edge(self, work: Rect, edge: str, thickness: int) -> None:
        bar = taskbar_of(monitor(PRIMARY_BOUNDS, work))

        assert bar is not None
        assert (bar.edge, bar.thickness_px) == (edge, thickness)

    def test_nothing_reserved_means_no_taskbar(self) -> None:
        # What an auto-hidden taskbar looks like -- and the honest answer, since
        # a hidden bar covers nothing.
        assert taskbar_of(monitor(PRIMARY_BOUNDS)) is None

    def test_the_thickest_edge_wins_when_two_are_reserved(self) -> None:
        # A second docked appbar alongside the taskbar.
        both = monitor(PRIMARY_BOUNDS, Rect(0, 40, 2880, 1704))

        bar = taskbar_of(both)

        assert bar is not None
        assert (bar.edge, bar.thickness_px) == (Edge.BOTTOM, 96)

    def test_a_negative_origin_monitor_measures_its_own_bar(self) -> None:
        left = monitor(Rect(-1920, 0, 0, 1080), Rect(-1920, 0, 0, 1032))

        bar = taskbar_of(left)

        assert bar is not None
        assert (bar.edge, bar.thickness_px) == (Edge.BOTTOM, 48)


class TestJoinByRect:
    def test_joins_the_real_two_monitor_desktop(self) -> None:
        displays = join_by_rect(ENUMERATED, COM_RECTS)

        assert [d.wallpaper_id for d in displays] == ["id-primary", "id-second"]
        assert [d.device for d in displays] == [r"\\.\DISPLAY1", r"\\.\DISPLAY5"]

    def test_ignores_remembered_but_disconnected_monitors(self) -> None:
        # GetMonitorDevicePathCount reported 4 for 2 attached screens; the
        # caller drops the two whose GetMonitorRECT failed, so they never reach
        # here. What does arrive is simply a shorter list -- no error.
        displays = join_by_rect(ENUMERATED, COM_RECTS)

        assert len(displays) == 2

    def test_primary_comes_first(self) -> None:
        # apply_wallpaper falls back to element 0, so this ordering is load
        # bearing, not cosmetic.
        reversed_order = (ENUMERATED[1], ENUMERATED[0])

        displays = join_by_rect(reversed_order, COM_RECTS)

        assert displays[0].monitor.primary

    def test_then_left_to_right(self) -> None:
        left = monitor(Rect(-1920, 0, 0, 1080))
        right = monitor(Rect(2880, 0, 4800, 1080))
        enumerated = ((right, "R"), (PRIMARY, "P"), (left, "L"))
        rects = (("id-r", right.bounds), ("id-p", PRIMARY.bounds), ("id-l", left.bounds))

        displays = join_by_rect(enumerated, rects)

        assert [d.device for d in displays] == ["P", "L", "R"]

    def test_a_monitor_with_no_wallpaper_id_abandons_the_attempt(self) -> None:
        # Setting the right image on the wrong screen is worse than setting one
        # image everywhere, so an unmatched monitor means "do not attempt".
        assert join_by_rect(ENUMERATED, (COM_RECTS[0],)) == ()

    def test_cloned_displays_abandon_the_attempt(self) -> None:
        # Two monitors reporting the same rectangle: a dict keyed by rect would
        # silently drop one and look like it succeeded.
        cloned = (("id-a", PRIMARY_BOUNDS), ("id-b", PRIMARY_BOUNDS))

        assert join_by_rect(ENUMERATED, cloned) == ()

    def test_duplicate_enumeration_abandons_the_attempt(self) -> None:
        duplicated = ((PRIMARY, r"\\.\DISPLAY1"), (PRIMARY, r"\\.\DISPLAY2"))

        assert join_by_rect(duplicated, COM_RECTS) == ()

    def test_no_monitors_joins_to_nothing(self) -> None:
        assert join_by_rect((), ()) == ()

    def test_the_join_is_by_rectangle_not_by_order(self) -> None:
        swapped = (COM_RECTS[1], COM_RECTS[0])

        displays = join_by_rect(ENUMERATED, swapped)

        assert displays[0].wallpaper_id == "id-primary"
        assert displays[1].wallpaper_id == "id-second"


class TestDisplay:
    def test_carries_the_geometry_its_wallpaper_needs(self) -> None:
        display = Display(monitor=SECOND, device=r"\\.\DISPLAY5", wallpaper_id="id")

        assert screen_of(display.monitor).width_px == 1920
        assert taskbar_of(display.monitor).thickness_px == 48
