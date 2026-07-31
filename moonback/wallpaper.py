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

logger = logging.getLogger(__name__)

#: SPI_SETDESKWALLPAPER, plus SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE.
_SPI_SETDESKWALLPAPER = 20
_SPIF_PERSIST_AND_BROADCAST = 3


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
    headline: str | None = None,
) -> Path:
    """Centre the moon frame on the star canvas, caption it, and write the result.

    One ImageMagick invocation, not two: the previous composite-then-annotate
    pair read and rewrote a ~57 MB TIFF twice per run for no benefit. Text is
    passed to ``-annotate`` as its own argv element rather than interpolated
    into a ``-draw`` program, so its content is never parsed.
    """
    offset_x, offset_y = profile.caption_offset
    headline_size = round(profile.point_size * 0.82)
    # Gravity east measures y downward from the vertical centre, so the
    # headline needs a smaller offset than the caption to sit above it.
    headline_y = offset_y - round(profile.point_size * HEADLINE_LEADING)

    command = [
        magick,
        str(canvas),
        str(moon),
        "-gravity", "center", "-composite",
        "-font", "Verdana",
        "-gravity", "east",
    ]  # fmt: skip

    if headline:
        command += [
            "-fill", HEADLINE_COLOUR,
            "-pointsize", str(headline_size),
            "-annotate", f"+{offset_x}+{headline_y}", headline,
        ]  # fmt: skip

    command += [
        "-fill", "white",
        "-pointsize", str(profile.point_size),
        "-annotate", f"+{offset_x}+{offset_y}", caption,
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
