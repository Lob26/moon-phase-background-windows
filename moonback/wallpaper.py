"""Compositing the wallpaper and handing it to Windows.

The two OS-facing operations live together here so the rest of the package
stays importable (and testable) on any platform: ``ctypes.windll`` only exists
on Windows, so it is imported inside the one function that needs it.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import RenderProfile
from .layout import Edge, Placement, Screen, Taskbar, place

logger = logging.getLogger(__name__)

#: SPI_SETDESKWALLPAPER, plus SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE.
_SPI_SETDESKWALLPAPER = 20
_SPIF_PERSIST_AND_BROADCAST = 3

#: SHAppBarMessage(ABM_GETTASKBARPOS) and the ABE_* edge codes it returns.
_ABM_GETTASKBARPOS = 0x00000005
_EDGES = {0: Edge.LEFT, 1: Edge.TOP, 2: Edge.RIGHT, 3: Edge.BOTTOM}
_SM_CXSCREEN, _SM_CYSCREEN = 0, 1


class RenderError(Exception):
    """ImageMagick failed. The message carries its stderr."""


#: The headline sits above the caption in warm amber, so "there is an eclipse
#: and you can see it from here" reads differently from the routine numbers.
HEADLINE_COLOUR = "#ffc66d"

#: Headline baseline offset above the caption, as a multiple of the caption's
#: point size. Keeps the two lines proportional across both profiles.
HEADLINE_LEADING = 1.7


def compose(
    magick: str,
    *,
    canvas: Path,
    moon: Path,
    caption: str,
    profile: RenderProfile,
    destination: Path,
    placement: Placement,
    headline: str | None = None,
) -> Path:
    """Centre the moon frame on the star canvas, caption it, and write the result.

    One ImageMagick invocation, not two: the previous composite-then-annotate
    pair read and rewrote a ~57 MB TIFF twice per run for no benefit. Text is
    passed to ``-annotate`` as its own argv element rather than interpolated
    into a ``-draw`` program, so its content is never parsed.
    """
    spot = placement
    logger.debug("Caption at %s %+d%+d", spot.gravity, spot.x, spot.caption_y)

    command = [
        magick,
        str(canvas),
        str(moon),
        "-gravity", "center", "-composite",
        "-font", "Verdana",
        "-gravity", spot.gravity,
    ]  # fmt: skip

    if headline:
        command += [
            "-fill", HEADLINE_COLOUR,
            "-pointsize", str(round(profile.point_size * 0.82)),
            "-annotate", f"+{spot.x}+{spot.headline_y}", headline,
        ]  # fmt: skip

    command += [
        "-fill", "white",
        "-pointsize", str(profile.point_size),
        "-annotate", f"+{spot.x}+{spot.caption_y}", caption,
        # The NASA frames carry an alpha channel the star canvas does not. Left
        # on, it survives into the output and costs a third more disk for a
        # wallpaper that is opaque by definition.
        "-alpha", "off",
        str(destination),
    ]  # fmt: skip

    logger.debug("Running %s", " ".join(command))
    # check=False on purpose: CalledProcessError's message drops stderr, which is
    # exactly the detail needed to tell "no such font" from "cannot write output".
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RenderError(
            f"ImageMagick exited {result.returncode} while composing {destination.name}: "
            f"{result.stderr.strip() or '<no stderr>'}"
        )
    if result.stderr.strip():
        logger.warning("ImageMagick: %s", result.stderr.strip())
    return destination


def resolve_placement(profile: RenderProfile, corner: str) -> Placement:
    """Work out where the caption goes, asking Windows about the taskbar.

    Queried per run rather than at install time: the taskbar gets moved and
    screens get plugged in.
    """
    taskbar, screen = detect_desktop()
    return place(
        corner,
        canvas_width=profile.canvas_width,
        canvas_height=profile.canvas_height,
        margin=profile.caption_margin,
        leading=round(profile.point_size * HEADLINE_LEADING),
        taskbar=taskbar,
        screen=screen,
    )


def detect_desktop() -> tuple[Taskbar | None, Screen | None]:
    """Ask Windows where the taskbar is and how big the primary screen is.

    Best effort: on any failure the caller just places the caption without a
    taskbar allowance, which is what every version before this did anyway.
    """
    try:
        import ctypes  # noqa: PLC0415 - Windows-only, see set_wallpaper
        from ctypes import wintypes  # noqa: PLC0415

        class APPBARDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT),
                ("rc", wintypes.RECT),
                ("lParam", wintypes.LPARAM),
            ]

        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(APPBARDATA)
        if not ctypes.windll.shell32.SHAppBarMessage(_ABM_GETTASKBARPOS, ctypes.byref(data)):
            return None, None

        edge = _EDGES.get(data.uEdge)
        if edge is None:
            return None, None

        width = data.rc.right - data.rc.left
        height = data.rc.bottom - data.rc.top
        thickness = height if edge in {Edge.TOP, Edge.BOTTOM} else width

        screen = Screen(
            width_px=ctypes.windll.user32.GetSystemMetrics(_SM_CXSCREEN),
            height_px=ctypes.windll.user32.GetSystemMetrics(_SM_CYSCREEN),
        )
        logger.debug("Taskbar on the %s, %d px thick; screen %dx%d",
                     edge, thickness, screen.width_px, screen.height_px)  # fmt: skip
        return Taskbar(edge=edge, thickness_px=thickness), screen
    except Exception as exc:  # noqa: BLE001 - cosmetic, never worth failing a run
        logger.warning("Could not read the taskbar position (%s); placing without it", exc)
        return None, None


def set_wallpaper(path: Path) -> None:
    """Point the Windows desktop at ``path``."""
    # Imported here, not at module scope: ctypes.windll exists only on Windows,
    # and everything else in this package must stay importable (and testable)
    # on any platform.
    from ctypes import windll  # noqa: PLC0415

    ok = windll.user32.SystemParametersInfoW(
        _SPI_SETDESKWALLPAPER, 0, str(path), _SPIF_PERSIST_AND_BROADCAST
    )
    if not ok:
        raise RenderError(f"SystemParametersInfoW refused to set the wallpaper to {path}")
