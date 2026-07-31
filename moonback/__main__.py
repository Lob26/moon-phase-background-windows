"""Entry point: resolve config, fetch the hour's frame, render, set, clean up."""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from . import __version__
from .config import Config, ConfigError, OnError, load_config
from .eclipses import EclipseError, describe_at, parse_eclipses
from .moondata import (
    MoonDataError,
    MoonHour,
    format_caption,
    frame_filename,
    parse_mooninfo,
    select_hour,
)
from .nasa import DownloadError, download
from .visibility import altitude_degrees
from .visibility import describe as describe_visibility
from .wallpaper import RenderError, compose, resolve_placement, set_wallpaper

logger = logging.getLogger("moonback")


def _configure_logging(log_file: Path) -> None:
    logging.basicConfig(
        force=True,
        filename=log_file,
        level=logging.DEBUG,
        format="[%(levelname)s] %(asctime)s %(name)s - %(message)s",
    )
    # httpx/httpcore at DEBUG dump every response header, which on this host
    # means a 2 KB CSP blob per hourly run. Their warnings still get through.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def eclipse_note(config: Config, moment: datetime) -> str | None:
    """Describe an eclipse in progress, or None.

    Best effort by design: the catalogue is an adornment, and a wallpaper that
    refuses to update because an optional data file is unreadable would be a
    worse bug than a missing caption.
    """
    try:
        catalogue = parse_eclipses(config.eclipse_path.read_text(encoding="utf-8"))
    except (OSError, EclipseError) as exc:
        logger.warning("Eclipse catalogue unavailable (%s); captioning without it", exc)
        return None

    note = describe_at(catalogue, moment)
    if note:
        logger.info("Eclipse in progress: %s", note)
    return note


def visibility_headline(config: Config, hour: MoonHour, moment: datetime) -> str | None:
    """Say whether the eclipse is actually above the horizon from the configured place.

    "There is an eclipse" and "you can go outside and see it" are different
    claims, and only the second one is worth shouting about. Returns None when
    no location is configured -- an unanswered install question must not put
    words on the wallpaper.
    """
    if config.observer is None:
        return None

    altitude = altitude_degrees(
        config.observer,
        moment,
        right_ascension_hours=hour.right_ascension_hours,
        declination_degrees=hour.declination_degrees,
    )
    headline = describe_visibility(config.observer, altitude)
    logger.info(
        "Moon altitude from %s: %.1f degrees (%s)",
        config.observer.name,
        altitude,
        headline or "below the horizon",
    )
    return headline


def ensure_ephemeris(client: httpx.Client, config: Config) -> Path:
    """Return the year's ephemeris, fetching and caching it on first miss.

    This is what makes the January rollover self-healing: once a year's SVS id
    is known, the first hourly run of that year downloads the table it needs.
    The existing Task Scheduler trigger is the only scheduler involved.
    """
    path = config.ephemeris_path
    if path.is_file():
        return path

    logger.info("No cached ephemeris for %d; fetching %s", config.year, config.mooninfo_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    return download(
        client,
        config.mooninfo_url,
        path,
        attempts=config.attempts,
        not_found_hint=f"the SVS collection id mapped for {config.year} is probably wrong",
    )


def run(config: Config, now: datetime | None = None) -> str:
    """Do one wallpaper update and return the caption that was drawn."""
    now = now or datetime.now(UTC)

    timeout = httpx.Timeout(
        connect=config.connect_timeout,
        read=config.read_timeout,
        write=config.connect_timeout,
        pool=config.connect_timeout,
    )

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        ephemeris = ensure_ephemeris(client, config)
        rows = parse_mooninfo(ephemeris.read_text(encoding="utf-8"))
        hour, index = select_hour(rows, now)
        logger.info(
            "Hour %d of %d: %.2f%% illuminated, %.3f days into the cycle",
            index,
            config.year,
            hour.illumination_pct,
            hour.cycle_age_days,
        )

        note = eclipse_note(config, now)
        caption = format_caption(hour, note)
        headline = visibility_headline(config, hour, now) if note else None

        placement = resolve_placement(config.profile, config.caption_corner)

        filename = frame_filename(index)
        frame = config.home / filename
        try:
            download(
                client,
                config.frame_url(filename),
                frame,
                attempts=config.attempts,
                not_found_hint="the frame number or this year's SVS collection id is wrong",
            )
            compose(
                config.magick,
                canvas=config.canvas_path,
                moon=frame,
                caption=caption,
                profile=config.profile,
                destination=config.output_path,
                placement=placement,
                headline=headline,
            )
        finally:
            # The frames are ~4 MB each and one is downloaded every hour;
            # leaving them behind after a failure is how a checkout fills a disk.
            frame.unlink(missing_ok=True)

    set_wallpaper(config.output_path)
    logger.info("Wallpaper set: %s", caption)
    return caption


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in {"-V", "--version"}:
        print(f"moonback {__version__}")
        return 0

    try:
        config = load_config()
    except ConfigError as exc:
        # Logging is not configured yet -- the log path itself comes from config.
        print(f"moonback: {exc}", file=sys.stderr)
        return 2

    _configure_logging(config.log_file)
    logger.info(
        "Starting moonback %s (profile=%s, year=%d)",
        __version__,
        config.profile.name,
        config.year,
    )

    try:
        print(run(config))
    except (MoonDataError, DownloadError, RenderError) as exc:
        logger.error("%s: %s", type(exc).__name__, exc)
        print(f"moonback: {exc}", file=sys.stderr)
        if config.on_error == OnError.QUIET:
            # Chosen at install time: keep the previous wallpaper and report
            # success, so an offline laptop does not light up Task Scheduler.
            # The failure is in mbg.log either way.
            logger.info("on_error=quiet: reporting success and keeping the previous wallpaper")
            return 0
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
