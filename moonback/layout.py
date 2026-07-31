"""Where the caption goes, given a corner and whatever the taskbar is covering.

Pure: the OS query lives in wallpaper.py and its results are passed in here, so
the placement arithmetic is testable without a desktop.

The canvas is 3:2 and most screens are 16:9, so Windows' "Fill" crops the top
and bottom before showing it. Screen pixels are therefore converted to canvas
pixels by the *width* ratio, which Fill preserves.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Gravity for each corner, and the sign of the taskbar edges that can cover it.
_CORNERS: dict[str, tuple[str, str, str]] = {
    # corner            gravity      vertical edge   horizontal edge
    "bottom-right": ("southeast", "bottom", "right"),
    "bottom-left": ("southwest", "bottom", "left"),
    "top-right": ("northeast", "top", "right"),
    "top-left": ("northwest", "top", "left"),
}

CORNERS = tuple(_CORNERS)


class Edge:
    LEFT = "left"
    TOP = "top"
    RIGHT = "right"
    BOTTOM = "bottom"


@dataclass(frozen=True, slots=True)
class Taskbar:
    """Which screen edge the taskbar is docked to, and how thick it is."""

    edge: str
    thickness_px: int


@dataclass(frozen=True, slots=True)
class Screen:
    width_px: int
    height_px: int


@dataclass(frozen=True, slots=True)
class Placement:
    """ImageMagick gravity and offsets, in canvas pixels."""

    gravity: str
    x: int
    caption_y: int
    headline_y: int


def taskbar_in_canvas_pixels(
    taskbar: Taskbar | None, screen: Screen | None, canvas_width: int
) -> int:
    """Convert the taskbar's thickness into canvas pixels, or 0 if unknown."""
    if taskbar is None or screen is None or screen.width_px <= 0:
        return 0
    return round(taskbar.thickness_px * canvas_width / screen.width_px)


def place(
    corner: str,
    *,
    canvas_width: int,
    canvas_height: int,
    margin: tuple[int, int],
    leading: int,
    taskbar: Taskbar | None = None,
    screen: Screen | None = None,
) -> Placement:
    """Resolve a corner into gravity and offsets, pushed clear of the taskbar.

    ``margin`` is the (x, y) inset from the chosen corner and ``leading`` the
    gap between the caption and the headline above it. Both are in canvas
    pixels so the two render profiles stay proportional.
    """
    if corner not in _CORNERS:
        raise ValueError(f"unknown corner {corner!r}; choose one of {', '.join(CORNERS)}")

    gravity, vertical_edge, horizontal_edge = _CORNERS[corner]
    margin_x, margin_y = margin

    # Only a taskbar on one of *this* corner's own edges can cover the caption.
    if taskbar is not None:
        inset = taskbar_in_canvas_pixels(taskbar, screen, canvas_width)
        if taskbar.edge == vertical_edge:
            margin_y += inset
        elif taskbar.edge == horizontal_edge:
            margin_x += inset

    # Gravity measures y inward from the corner's own edge, so the headline is
    # always further in than the caption regardless of which corner this is.
    return Placement(
        gravity=gravity,
        x=margin_x,
        caption_y=margin_y,
        headline_y=margin_y + leading,
    )
