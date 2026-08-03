"""Planning what to render, and the ImageMagick command line that renders it.

No ImageMagick and no desktop: `subprocess.run` is stubbed, and the OS lookups
are injected as plain data. The suite runs on ubuntu in CI.

The load-bearing test here is `test_the_fallback_command_is_unchanged`. Adding
per-monitor rendering must not alter a single argument of the command the
single-monitor path emits, because that path is what most installs use.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from moonback import wallpaper
from moonback.config import PROFILES
from moonback.layout import Placement, Screen, place_native
from moonback.monitors import Display, Monitor, Rect
from moonback.wallpaper import (
    HEADLINE_SCALE,
    RenderError,
    Target,
    apply_wallpaper,
    caption_size,
    compose,
    plan_targets,
)

STANDARD = PROFILES["standard"]
LARGE = PROFILES["large"]

PRIMARY = Monitor(bounds=Rect(0, 0, 2880, 1800), work=Rect(0, 0, 2880, 1704), primary=True)
SECOND = Monitor(bounds=Rect(2880, 0, 4800, 1080), work=Rect(2880, 0, 4800, 1032), primary=False)
DISPLAYS = (
    Display(monitor=PRIMARY, device=r"\\.\DISPLAY1", wallpaper_id="id-primary"),
    Display(monitor=SECOND, device=r"\\.\DISPLAY5", wallpaper_id="id-second"),
)

SPOT = place_native("bottom-right", screen=Screen(2880, 1800), point_size=26)


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture the argv compose() would have run."""
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wallpaper.subprocess, "run", fake_run)
    return calls


def run_compose(recorded: list[list[str]], **kwargs) -> list[str]:
    compose(
        "magick",
        canvas=Path("best_small.tif"),
        moon=Path("moon.0001.tif"),
        caption="Phase: 94.03% Days: 17.678",
        destination=Path("back.tif"),
        placement=SPOT,
        **kwargs,
    )
    return recorded[0]


class TestCaptionSize:
    def test_matches_what_fill_used_to_show(self) -> None:
        # 50 pt drawn on the canvas, then scaled by 2880/5461, has always
        # appeared as ~26 px. Pre-scaling means annotating at 26.
        assert caption_size(STANDARD, Screen(2880, 1800)) == 26

    def test_a_smaller_screen_gets_a_smaller_caption(self) -> None:
        assert caption_size(STANDARD, Screen(1920, 1080)) == 18

    def test_scales_with_the_profile(self) -> None:
        assert caption_size(LARGE, Screen(2880, 1800)) > caption_size(STANDARD, Screen(2880, 1800))

    def test_never_collapses_to_zero(self) -> None:
        # A tiny virtual display must not produce -pointsize 0.
        assert caption_size(STANDARD, Screen(64, 64)) >= 1


class TestPlanTargets:
    def test_one_target_per_display_numbered_from_one(self) -> None:
        outputs = [Path("back-1.tif"), Path("back-2.tif")]

        targets = plan_targets(STANDARD, "bottom-right", DISPLAYS, outputs)

        assert [t.destination.name for t in targets] == ["back-1.tif", "back-2.tif"]

    def test_each_target_renders_at_its_own_monitor_size(self) -> None:
        targets = plan_targets(
            STANDARD, "bottom-right", DISPLAYS, [Path("a.tif"), Path("b.tif")]
        )

        assert targets[0].render == Screen(2880, 1800)
        assert targets[1].render == Screen(1920, 1080)

    def test_render_uses_the_full_bounds_not_the_work_area(self) -> None:
        # The wallpaper covers the whole monitor; the taskbar sits on top.
        targets = plan_targets(STANDARD, "bottom-right", DISPLAYS[:1], [Path("a.tif")])

        assert targets[0].render.height_px == 1800

    def test_each_monitor_gets_its_own_taskbar_allowance(self) -> None:
        # The point of the change: 96 px on the primary, 48 on the secondary.
        targets = plan_targets(
            STANDARD, "bottom-right", DISPLAYS, [Path("a.tif"), Path("b.tif")]
        )

        assert targets[0].placement.caption_y == 45 + 96
        assert targets[1].placement.caption_y == 27 + 48

    def test_carries_the_wallpaper_id(self) -> None:
        targets = plan_targets(
            STANDARD, "bottom-right", DISPLAYS, [Path("a.tif"), Path("b.tif")]
        )

        assert [t.monitor_id for t in targets] == ["id-primary", "id-second"]

    def test_mismatched_outputs_are_a_programming_error(self) -> None:
        # zip(strict=True): one output per display or nothing.
        with pytest.raises(ValueError, match="shorter"):
            plan_targets(STANDARD, "bottom-right", DISPLAYS, [Path("only-one.tif")])


class TestComposeCommand:
    def test_the_fallback_command_is_unchanged(self, recorded) -> None:
        """render=None must emit exactly what it emitted before per-monitor."""
        command = run_compose(recorded)

        assert command == [
            "magick",
            "best_small.tif",
            "moon.0001.tif",
            "-gravity", "center", "-composite",
            "-font", "Verdana",
            "-gravity", "southeast",
            "-fill", "white",
            "-pointsize", "26",
            "-annotate", "+45+45", "Phase: 94.03% Days: 17.678",
            "-alpha", "off",
            "back.tif",
        ]  # fmt: skip

    def test_a_render_size_crops_to_the_screen(self, recorded) -> None:
        command = run_compose(recorded, render=Screen(2880, 1800))

        assert "-resize" in command
        assert command[command.index("-resize") + 1] == "2880x1800^"
        assert command[command.index("-extent") + 1] == "2880x1800"

    def test_the_crop_happens_before_the_text(self, recorded) -> None:
        # Otherwise the caption would be scaled and cropped along with the moon,
        # and the offsets would not be screen pixels at all.
        command = run_compose(recorded, render=Screen(1920, 1080))

        assert command.index("-composite") < command.index("-resize")
        assert command.index("-extent") < command.index("-annotate")

    def test_the_crop_pads_with_black(self, recorded) -> None:
        # `-resize ^` can round a pixel short of the box; without a background
        # -extent would pad it with whatever was left over.
        command = run_compose(recorded, render=Screen(2880, 1800))

        assert command[command.index("-background") + 1] == "black"

    def test_the_caption_uses_the_placement_point_size(self, recorded) -> None:
        spot = Placement(gravity="northwest", x=10, caption_y=20, headline_y=60, point_size=18)
        compose(
            "magick",
            canvas=Path("c.tif"),
            moon=Path("m.tif"),
            caption="hi",
            destination=Path("o.tif"),
            placement=spot,
        )

        command = recorded[0]
        assert command[command.index("-pointsize") + 1] == "18"

    def test_the_headline_is_drawn_smaller_and_above(self, recorded) -> None:
        command = run_compose(recorded, headline="VISIBLE FROM BOGOTA - LOOK UP")

        assert "VISIBLE FROM BOGOTA - LOOK UP" in command
        assert str(round(SPOT.point_size * HEADLINE_SCALE)) in command
        assert command.index("VISIBLE FROM BOGOTA - LOOK UP") < command.index(
            "Phase: 94.03% Days: 17.678"
        )

    def test_the_text_is_its_own_argument(self, recorded) -> None:
        # Never interpolated into a -draw program, so its content is not parsed.
        command = run_compose(recorded, render=Screen(2880, 1800))

        assert "Phase: 94.03% Days: 17.678" in command

    def test_a_failure_carries_imagemagick_stderr(self, monkeypatch) -> None:
        def failing(command, **_kwargs):
            return subprocess.CompletedProcess(command, 1, "", "unable to read font")

        monkeypatch.setattr(wallpaper.subprocess, "run", failing)

        with pytest.raises(RenderError, match="unable to read font"):
            compose(
                "magick",
                canvas=Path("c.tif"),
                moon=Path("m.tif"),
                caption="hi",
                destination=Path("o.tif"),
                placement=SPOT,
            )


class TestApplyWallpaper:
    def test_a_single_target_uses_the_whole_desktop_api(self, monkeypatch) -> None:
        used: list[Path] = []
        monkeypatch.setattr(wallpaper, "set_wallpaper", used.append)
        monkeypatch.setattr(
            wallpaper, "set_per_monitor", lambda _a: pytest.fail("should not be called")
        )

        apply_wallpaper((Target(destination=Path("back.tif"), placement=SPOT),))

        assert used == [Path("back.tif")]

    def test_every_monitor_set_means_no_fallback(self, monkeypatch) -> None:
        monkeypatch.setattr(wallpaper, "set_per_monitor", len)
        monkeypatch.setattr(
            wallpaper, "set_wallpaper", lambda _p: pytest.fail("should not fall back")
        )

        apply_wallpaper(
            (
                Target(Path("back-1.tif"), SPOT, monitor_id="a"),
                Target(Path("back-2.tif"), SPOT, monitor_id="b"),
            )
        )

    def test_a_partial_result_falls_back_to_one_image(self, monkeypatch) -> None:
        # One screen updated and another not is more confusing than one
        # consistent image everywhere.
        used: list[Path] = []
        monkeypatch.setattr(wallpaper, "set_per_monitor", lambda _a: 1)
        monkeypatch.setattr(wallpaper, "set_wallpaper", used.append)

        apply_wallpaper(
            (
                Target(Path("back-1.tif"), SPOT, monitor_id="a"),
                Target(Path("back-2.tif"), SPOT, monitor_id="b"),
            )
        )

        assert used == [Path("back-1.tif")], "falls back to the primary's image"


class TestResolveTargets:
    def test_a_preview_never_fans_out(self, monkeypatch) -> None:
        monkeypatch.setattr(
            wallpaper, "detect_displays", lambda: pytest.fail("must not probe for a preview")
        )
        monkeypatch.setattr(
            wallpaper, "resolve_placement", lambda _p, _c: SPOT
        )

        targets = wallpaper.resolve_targets(_config(), Path("preview.tif"), per_monitor=False)

        assert len(targets) == 1
        assert targets[0].render is None
        assert targets[0].monitor_id is None

    def test_one_monitor_takes_the_single_path(self, monkeypatch) -> None:
        monkeypatch.setattr(wallpaper, "detect_displays", lambda: DISPLAYS[:1])
        monkeypatch.setattr(wallpaper, "resolve_placement", lambda _p, _c: SPOT)

        targets = wallpaper.resolve_targets(_config(), Path("back.tif"), per_monitor=True)

        assert len(targets) == 1
        assert targets[0].render is None

    def test_no_displays_takes_the_single_path(self, monkeypatch) -> None:
        # What a machine without usable COM looks like.
        monkeypatch.setattr(wallpaper, "detect_displays", lambda: ())
        monkeypatch.setattr(wallpaper, "resolve_placement", lambda _p, _c: SPOT)

        targets = wallpaper.resolve_targets(_config(), Path("back.tif"), per_monitor=True)

        assert (len(targets), targets[0].destination) == (1, Path("back.tif"))

    def test_two_monitors_fan_out(self, monkeypatch) -> None:
        monkeypatch.setattr(wallpaper, "detect_displays", lambda: DISPLAYS)

        targets = wallpaper.resolve_targets(_config(), Path("back.tif"), per_monitor=True)

        assert [t.destination.name for t in targets] == ["back-1.tif", "back-2.tif"]
        assert all(t.render is not None for t in targets)


class _Config:
    """Just the attributes resolve_targets reaches for."""

    profile = STANDARD
    caption_corner = "bottom-right"

    def monitor_output_path(self, index: int) -> Path:
        return Path(f"back-{index}.tif")


def _config() -> _Config:
    return _Config()
