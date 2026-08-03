"""Compositing the wallpaper and handing it to Windows.

The two OS-facing operations live together here so the rest of the package
stays importable (and testable) on any platform: ``ctypes.windll`` only exists
on Windows, so it is imported inside the one function that needs it.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .config import RenderProfile
from .layout import Edge, Placement, Screen, Taskbar, fit_to_screen, place, place_native
from .monitors import (
    MIN_PER_MONITOR,
    Display,
    detect_displays,
    screen_of,
    set_per_monitor,
    taskbar_of,
)

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

#: The headline is drawn a little smaller than the caption it sits above.
HEADLINE_SCALE = 0.82


def compose(
    magick: str,
    *,
    canvas: Path,
    moon: Path,
    caption: str,
    destination: Path,
    placement: Placement,
    render: Screen | None = None,
    moon_scale: float = 1.0,
    headline: str | None = None,
) -> Path:
    """Centre the moon frame on the star canvas, caption it, and write the result.

    One ImageMagick invocation, not two: the previous composite-then-annotate
    pair read and rewrote a ~57 MB TIFF twice per run for no benefit. Text is
    passed to ``-annotate`` as its own argv element rather than interpolated
    into a ``-draw`` program, so its content is never parsed.

    ``render`` crops the result to a screen's exact pixels, the way Windows
    "Fill" otherwise would, so the caption can be positioned in real screen
    coordinates. Left as None the whole canvas is written and Windows does the
    cropping, which is what the single-monitor path still wants.

    ``moon_scale`` shrinks the Moon before compositing so it survives that crop
    on a screen wider than the canvas. At 1.0 -- every conventional aspect
    ratio -- nothing is emitted for it and the frame is composited untouched.
    """
    spot = placement
    logger.debug("Caption at %s %+d%+d", spot.gravity, spot.x, spot.caption_y)

    command = [magick, str(canvas)]

    if moon_scale < 1.0:
        # Parenthesised so the resize applies to the moon alone and not to the
        # canvas already on the stack.
        logger.info("Shrinking the Moon to %.1f%% so it fits the screen", 100 * moon_scale)
        command += ["(", str(moon), "-resize", f"{moon_scale * 100:.4f}%", ")"]
    else:
        command += [str(moon)]

    command += ["-gravity", "center", "-composite"]

    if render is not None:
        # `^` fills the box and overflows; -extent then trims to it. The
        # background guards the pixel -extent can leave when `^` rounds down.
        size = f"{render.width_px}x{render.height_px}"
        command += [
            "-background", "black",
            "-resize", f"{size}^",
            "-gravity", "center",
            "-extent", size,
        ]  # fmt: skip

    command += [
        "-font", "Verdana",
        "-gravity", spot.gravity,
    ]  # fmt: skip

    if headline:
        command += [
            "-fill", HEADLINE_COLOUR,
            "-pointsize", str(round(spot.point_size * HEADLINE_SCALE)),
            "-annotate", f"+{spot.x}+{spot.headline_y}", headline,
        ]  # fmt: skip

    command += [
        "-fill", "white",
        "-pointsize", str(spot.point_size),
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


def resolve_placement(profile: RenderProfile, corner: str) -> tuple[Placement, Screen | None]:
    """Where the caption goes on the whole-desktop image, and the screen it is for.

    Queried per run rather than at install time: the taskbar gets moved and
    screens get plugged in. The screen comes back alongside the placement
    because the Moon has to be sized against it too, and it may be None when
    detection fails -- in which case nothing is capped, exactly as before.
    """
    taskbar, screen = detect_desktop()
    placement = place(
        corner,
        canvas_width=profile.canvas_width,
        canvas_height=profile.canvas_height,
        margin=profile.caption_margin,
        point_size=profile.point_size,
        taskbar=taskbar,
        screen=screen,
    )
    return placement, screen


@dataclass(frozen=True, slots=True)
class Target:
    """One image to render, and where it belongs once rendered."""

    destination: Path
    placement: Placement

    render: Screen | None = None
    """Crop to this size, or None to write the whole canvas."""

    monitor_id: str | None = None
    """The COM id to set it on, or None to use the whole-desktop API."""

    screen: Screen | None = None
    """The display this image will end up on, if known.

    Deliberately not the same thing as ``render``: on the fallback path we may
    know the screen from ``detect_desktop()`` while still writing the whole
    canvas for Windows to crop. Knowing it is what lets a single ultrawide get
    its Moon capped.
    """


def caption_size(profile: RenderProfile, screen: Screen) -> int:
    """The point size that looks the same as the canvas-sized render did.

    ImageMagick draws at ``profile.point_size`` on the canvas and Windows then
    scales the whole canvas by ``fit.scale`` before you see it, so the apparent
    size has always been the product of the two. Pre-scaling ourselves means
    annotating at that product to land pixel-identical.
    """
    fit = fit_to_screen(profile.canvas_width, profile.canvas_height, screen)
    return max(1, round(profile.point_size * fit.scale))


def plan_targets(
    profile: RenderProfile,
    corner: str,
    displays: Sequence[Display],
    outputs: Sequence[Path],
) -> tuple[Target, ...]:
    """One render per display, each sized and positioned for its own screen."""
    targets = []
    for display, destination in zip(displays, outputs, strict=True):
        screen = screen_of(display.monitor)
        targets.append(
            Target(
                destination=destination,
                placement=place_native(
                    corner,
                    screen=screen,
                    point_size=caption_size(profile, screen),
                    taskbar=taskbar_of(display.monitor),
                ),
                render=screen,
                monitor_id=display.wallpaper_id,
                screen=screen,
            )
        )
    return tuple(targets)


def resolve_targets(config, output: Path, *, per_monitor: bool) -> tuple[Target, ...]:
    """Decide what to render: one image for the desktop, or one per monitor.

    Per-monitor needs more than one live screen *and* a usable COM interface.
    Everything else -- a single display, a preview, a machine where the shell
    will not talk to us -- takes the path this tool has always taken.
    """
    placement, screen = resolve_placement(config.profile, config.caption_corner)
    single = (Target(destination=output, placement=placement, screen=screen),)
    if not per_monitor:
        return single

    displays = detect_displays()
    if len(displays) < MIN_PER_MONITOR:
        logger.info("One monitor (or none detected); rendering a single wallpaper")
        return single

    outputs = [config.monitor_output_path(i) for i in range(1, len(displays) + 1)]
    return plan_targets(config.profile, config.caption_corner, displays, outputs)


def apply_wallpaper(targets: Sequence[Target]) -> None:
    """Put each rendered image on its monitor, or fall back to one for all.

    A partial per-monitor result still falls back, because a desktop where one
    screen updated and another did not is more confusing than one consistent
    image everywhere.
    """
    assignments = {t.monitor_id: t.destination for t in targets if t.monitor_id}

    if len(assignments) == len(targets) > 1:
        done = set_per_monitor(assignments)
        if done == len(assignments):
            logger.info("Wallpaper set on %d monitors", done)
            return
        logger.warning(
            "Only %d of %d monitors accepted a wallpaper; using a single image",
            done,
            len(assignments),
        )

    set_wallpaper(targets[0].destination)


def _become_dpi_aware() -> None:
    """Opt into physical pixels, so screen and taskbar are measured alike.

    Best effort and idempotent: both calls are no-ops once awareness is set,
    and shcore is absent before Windows 8.1.
    """
    import ctypes  # noqa: PLC0415

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            logger.debug("Could not set DPI awareness; sizes may be virtualised")


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

        # SHAppBarMessage always reports physical pixels, but GetSystemMetrics
        # reports DPI-virtualised ones unless the process opts in. Mixing them
        # made a 96 px taskbar on a 2880 px screen look like 96 on 1440 -- twice
        # as thick as it is -- and pushed the caption a sixth of the way up.
        _become_dpi_aware()

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
