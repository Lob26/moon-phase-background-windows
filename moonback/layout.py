"""Where the caption goes, given a corner and whatever the taskbar is covering.

Pure: the OS query lives in wallpaper.py and its results are passed in here, so
the placement arithmetic is testable without a desktop.

The hard part is that the canvas is never the shape of the screen. Windows
"Fill" scales the image to *cover* the display and crops the overflow, so the
outermost rows and columns of the canvas are never visible. An inset measured
from the canvas edge is therefore not the inset you see -- which is how the
caption ended up floating a sixth of the way up the screen instead of sitting
in a corner.

So the margin is specified in screen pixels and converted inward through the
crop, rather than the other way around.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Gravity for each corner, and the edges of the screen that corner touches.
_CORNERS: dict[str, tuple[str, str, str]] = {
    # corner            gravity      vertical edge   horizontal edge
    "bottom-right": ("southeast", "bottom", "right"),
    "bottom-left": ("southwest", "bottom", "left"),
    "top-right": ("northeast", "top", "right"),
    "top-left": ("northwest", "top", "left"),
}

CORNERS = tuple(_CORNERS)

#: Inset from the visible edge, as a fraction of screen height. About 45 px on
#: a 1800 px display: close enough to read as a corner, far enough to breathe.
CORNER_INSET = 0.025


class Edge:
    LEFT = "left"
    TOP = "top"
    RIGHT = "right"
    BOTTOM = "bottom"


@dataclass(frozen=True, slots=True)
class Taskbar:
    """Which screen edge the taskbar is docked to, and how thick it is.

    Thickness is in physical pixels, the units SHAppBarMessage reports in.
    """

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


@dataclass(frozen=True, slots=True)
class Fit:
    """How a canvas maps onto a screen under Windows "Fill"."""

    scale: float
    """Screen pixels per canvas pixel."""

    crop_x: int
    """Canvas columns hidden off each side."""

    crop_y: int
    """Canvas rows hidden off the top and bottom."""


def fit_to_screen(canvas_width: int, canvas_height: int, screen: Screen) -> Fit:
    """Work out the scale and cropping Windows "Fill" applies.

    Fill *covers* the screen, so the scale is the larger of the two ratios and
    the excess is cropped evenly. Whether that excess is horizontal or vertical
    depends on which is the wider aspect, so both are computed.
    """
    scale = max(screen.width_px / canvas_width, screen.height_px / canvas_height)
    visible_width = screen.width_px / scale
    visible_height = screen.height_px / scale
    return Fit(
        scale=scale,
        crop_x=round((canvas_width - visible_width) / 2),
        crop_y=round((canvas_height - visible_height) / 2),
    )


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
    """Resolve a corner into gravity and offsets, clear of the crop and taskbar.

    ``margin`` is the canvas-pixel fallback used when the screen is unknown --
    detection is best effort, and without it there is no way to know what is
    cropped. When the screen *is* known the inset is derived from it instead,
    so the caption sits the same visual distance from the corner on any display.
    """
    if corner not in _CORNERS:
        raise ValueError(f"unknown corner {corner!r}; choose one of {', '.join(CORNERS)}")

    gravity, vertical_edge, horizontal_edge = _CORNERS[corner]

    if screen is None:
        margin_x, margin_y = margin
    else:
        fit = fit_to_screen(canvas_width, canvas_height, screen)
        inset = screen.height_px * CORNER_INSET

        # Only a taskbar docked to one of this corner's own edges can cover it.
        edge = taskbar.edge if taskbar else None
        bar_x = taskbar.thickness_px if taskbar and edge == horizontal_edge else 0
        bar_y = taskbar.thickness_px if taskbar and edge == vertical_edge else 0

        margin_x = fit.crop_x + round((inset + bar_x) / fit.scale)
        margin_y = fit.crop_y + round((inset + bar_y) / fit.scale)

    # Gravity measures inward from the corner's own edges, so the headline is
    # always further in than the caption whichever corner this is.
    return Placement(
        gravity=gravity,
        x=margin_x,
        caption_y=margin_y,
        headline_y=margin_y + leading,
    )
