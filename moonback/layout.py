"""How the image maps onto a screen: what gets cropped, where the caption goes,
and how large the Moon is drawn.

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

#: Gap between the caption and the headline above it, as a multiple of the
#: caption's point size. It lives here rather than beside the ImageMagick call
#: because the point size is now decided per monitor, and the leading has to be
#: derived wherever the size is.
HEADLINE_LEADING = 1.7

#: Vertical field of view of NASA's render, in arcseconds.
#:
#: Not published by the SVS -- measured. The disc is proportional to the
#: ephemeris' own ``Diam`` column, so one number describes the whole mapping:
#:
#:   sample                  sequence      disc     Diam      disc/Diam
#:   03-midyear              Dial-A-Moon   1827 px  1770.7"   1.0318
#:   05-eclipse-visible      Dial-A-Moon   1895 px  1836.4"   1.0319
#:   07-eclipse-totality     telescopic    1938 px  1872.9"   1.0348
#:
#: The two Dial-A-Moon rows agree to 0.01%, and the per-eclipse telescopic
#: sequence lands within the error of thresholding a dim red disc -- so the
#: same field of view covers both. 2160 / 1.0318 = 2093.
MOON_FIELD_OF_VIEW_ARCSEC = 2093.0

#: Most of the screen's height the Moon may occupy before it gets shrunk.
#:
#: Chosen so that no conventional screen is ever touched: 16:9 reaches 67.5% at
#: perigee, and shrinking there would make a supermoon look like any other
#: night while the caption still called it one. Only 21:9 (80-91%) and 32:9
#: (119-135%, i.e. clipped) ever exceed it.
MAX_DISC_FRACTION = 0.70


class Edge:
    LEFT = "left"
    TOP = "top"
    RIGHT = "right"
    BOTTOM = "bottom"


@dataclass(frozen=True, slots=True)
class Taskbar:
    """Which screen edge the taskbar is docked to, and how thick it is.

    Thickness is in physical pixels: the units both SHAppBarMessage and the
    monitor rects report in.
    """

    edge: str
    thickness_px: int


@dataclass(frozen=True, slots=True)
class Screen:
    width_px: int
    height_px: int


@dataclass(frozen=True, slots=True)
class Placement:
    """Everything ImageMagick needs to draw the text, in output pixels.

    ``point_size`` travels with the offsets because it is decided per monitor:
    a caption sized for a 2880 px display would be half again too large on the
    1920 px one beside it.
    """

    gravity: str
    x: int
    caption_y: int
    headline_y: int
    point_size: int


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


def _corner_offsets(corner: str, taskbar: Taskbar | None) -> tuple[str, int, int]:
    """Gravity for ``corner``, and the taskbar allowance on each of its axes.

    Only a taskbar docked to one of this corner's *own* edges can cover it, so
    a bottom taskbar never shifts a top-corner caption sideways.
    """
    if corner not in _CORNERS:
        raise ValueError(f"unknown corner {corner!r}; choose one of {', '.join(CORNERS)}")

    gravity, vertical_edge, horizontal_edge = _CORNERS[corner]
    edge = taskbar.edge if taskbar else None
    bar_x = taskbar.thickness_px if taskbar and edge == horizontal_edge else 0
    bar_y = taskbar.thickness_px if taskbar and edge == vertical_edge else 0
    return gravity, bar_x, bar_y


def _placed(gravity: str, margin_x: int, margin_y: int, point_size: int) -> Placement:
    # Gravity measures inward from the corner's own edges, so the headline is
    # always further in than the caption whichever corner this is.
    return Placement(
        gravity=gravity,
        x=margin_x,
        caption_y=margin_y,
        headline_y=margin_y + round(point_size * HEADLINE_LEADING),
        point_size=point_size,
    )


def disc_fraction_of_frame(diameter_arcsec: float) -> float:
    """How much of the frame's height the lunar disc fills.

    Dimensionless on purpose: the same answer holds for a 2160-tall Dial-A-Moon
    frame and a 3240-tall one, because both render the same field of view.
    """
    return diameter_arcsec / MOON_FIELD_OF_VIEW_ARCSEC


def moon_scale(
    *,
    canvas_width: int,
    canvas_height: int,
    screen: Screen,
    frame_height_px: int,
    diameter_arcsec: float,
) -> float:
    """How much to shrink the Moon so it stays inside the screen. Never above 1.

    The Moon is composited onto the canvas at its own size, and the canvas is
    then scaled to *cover* the screen. On a display wider than the canvas that
    scale is driven by width while the visible height collapses, so the disc
    grows relative to what you can see -- past 3:2 it eventually runs off the
    top and bottom entirely.

    Returns 1.0 whenever the disc already fits, so ordinary screens render
    exactly as they always have and no resampling happens at all.
    """
    fit = fit_to_screen(canvas_width, canvas_height, screen)
    disc_px = frame_height_px * disc_fraction_of_frame(diameter_arcsec) * fit.scale
    if disc_px <= 0:
        return 1.0
    return min(1.0, MAX_DISC_FRACTION * screen.height_px / disc_px)


def place(
    corner: str,
    *,
    canvas_width: int,
    canvas_height: int,
    margin: tuple[int, int],
    point_size: int,
    taskbar: Taskbar | None = None,
    screen: Screen | None = None,
) -> Placement:
    """Place the caption on a canvas that Windows will crop to fit the screen.

    ``margin`` is the canvas-pixel fallback used when the screen is unknown --
    detection is best effort, and without it there is no way to know what is
    cropped. When the screen *is* known the inset is derived from it instead,
    so the caption sits the same visual distance from the corner on any display.

    Use :func:`place_native` when the image is already the size of the screen.
    """
    gravity, bar_x, bar_y = _corner_offsets(corner, taskbar)

    if screen is None:
        margin_x, margin_y = margin
    else:
        fit = fit_to_screen(canvas_width, canvas_height, screen)
        inset = screen.height_px * CORNER_INSET
        margin_x = fit.crop_x + round((inset + bar_x) / fit.scale)
        margin_y = fit.crop_y + round((inset + bar_y) / fit.scale)

    return _placed(gravity, margin_x, margin_y, point_size)


def place_native(
    corner: str,
    *,
    screen: Screen,
    point_size: int,
    taskbar: Taskbar | None = None,
) -> Placement:
    """Place the caption on an image already rendered at the screen's size.

    Nothing is cropped and nothing is scaled, so the offsets are simply the
    inset plus whatever the taskbar covers -- in real screen pixels.

    This is deliberately a separate function rather than a flag on
    :func:`place`: a ``native=True`` would silently make ``canvas_width`` and
    ``margin`` meaningless, which is exactly the unit confusion this module
    exists to prevent.
    """
    gravity, bar_x, bar_y = _corner_offsets(corner, taskbar)
    inset = round(screen.height_px * CORNER_INSET)
    return _placed(gravity, inset + bar_x, inset + bar_y, point_size)
