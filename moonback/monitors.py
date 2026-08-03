"""Finding the attached monitors, and the id Windows sets wallpaper by.

Two Win32 APIs are needed and neither is sufficient alone:

* ``EnumDisplayMonitors`` + ``GetMonitorInfoW`` give each monitor's bounds and
  its *work area* -- the part appbars leave free. Subtracting one from the
  other yields the taskbar edge and thickness **per monitor**, which
  ``SHAppBarMessage`` cannot express: it only ever reports the primary's.
* ``IDesktopWallpaper`` gives the opaque device-path id that
  ``SetWallpaper(monitorID, path)`` wants, but no work area.

They are joined on the monitor rectangle, which both report identically.

Only the last three functions touch the OS; everything above them is a pure
function of plain data, and ``ctypes`` is imported inside the functions that
need it so the package stays importable on any platform.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .layout import Edge, Screen, Taskbar

logger = logging.getLogger(__name__)

#: MONITORINFOF_PRIMARY
_PRIMARY_FLAG = 0x00000001

#: Below this many live monitors there is nothing per-monitor to do.
MIN_PER_MONITOR = 2


@dataclass(frozen=True, slots=True)
class Rect:
    """A screen rectangle in virtual-desktop coordinates.

    Origins can be negative -- a monitor placed left of or above the primary
    starts at a negative coordinate -- so only ever use the derived sizes.
    """

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class Monitor:
    """One display's physical bounds and the area appbars leave free."""

    bounds: Rect
    work: Rect
    primary: bool


@dataclass(frozen=True, slots=True)
class Display:
    """A live monitor joined to the id IDesktopWallpaper knows it by."""

    monitor: Monitor
    device: str
    """``\\\\.\\DISPLAY1`` and friends. For logging only -- not the wallpaper id."""

    wallpaper_id: str
    """The COM device path that ``SetWallpaper`` takes."""


def screen_of(monitor: Monitor) -> Screen:
    return Screen(width_px=monitor.bounds.width, height_px=monitor.bounds.height)


def taskbar_of(monitor: Monitor) -> Taskbar | None:
    """Derive the taskbar from the gap between the bounds and the work area.

    Returns the thickest reserved edge, or None when nothing is reserved --
    which is what an auto-hidden taskbar looks like, and is the honest answer:
    a hidden bar covers nothing.

    More than one edge can be reserved at once when a second appbar is docked;
    the thickest wins, ties resolving bottom, top, left, right, matching the
    order Windows itself prefers to dock in.
    """
    bounds, work = monitor.bounds, monitor.work
    gaps = (
        (Edge.BOTTOM, bounds.bottom - work.bottom),
        (Edge.TOP, work.top - bounds.top),
        (Edge.LEFT, work.left - bounds.left),
        (Edge.RIGHT, bounds.right - work.right),
    )
    edge, thickness = max(gaps, key=lambda gap: gap[1])
    return Taskbar(edge=edge, thickness_px=thickness) if thickness > 0 else None


def join_by_rect(
    enumerated: Sequence[tuple[Monitor, str]],
    wallpaper_rects: Sequence[tuple[str, Rect]],
) -> tuple[Display, ...]:
    """Match enumerated monitors to wallpaper ids on their shared rectangle.

    Returns () -- meaning "do not attempt per-monitor" -- when anything is
    ambiguous, because setting the right image on the wrong screen is worse
    than setting one image everywhere:

    * a monitor with no matching id, or an id we cannot place;
    * duplicate rectangles, which is what cloned displays look like.

    Ordered primary first, then left to right and top to bottom, so callers
    can rely on element 0 being the screen to fall back to.
    """
    by_rect: dict[Rect, str] = {}
    for wallpaper_id, rect in wallpaper_rects:
        if rect in by_rect:
            logger.info("Two monitors report the same rectangle (cloned?); not per-monitor")
            return ()
        by_rect[rect] = wallpaper_id

    seen: set[Rect] = set()
    displays: list[Display] = []
    for monitor, device in enumerated:
        if monitor.bounds in seen:
            logger.info("Duplicate monitor rectangle from enumeration; not per-monitor")
            return ()
        wallpaper_id = by_rect.get(monitor.bounds)
        if wallpaper_id is None:
            logger.info("Monitor %s has no wallpaper id; not per-monitor", device)
            return ()
        seen.add(monitor.bounds)
        displays.append(Display(monitor=monitor, device=device, wallpaper_id=wallpaper_id))

    displays.sort(
        key=lambda d: (not d.monitor.primary, d.monitor.bounds.left, d.monitor.bounds.top)
    )
    return tuple(displays)


# --------------------------------------------------------------------------
# Everything below here talks to Windows.
# --------------------------------------------------------------------------


def become_dpi_aware() -> None:
    """Opt into physical pixels, so every measurement shares one unit.

    Best effort and idempotent. **Must run before any monitor is measured**:
    without it ``GetMonitorInfo`` reports DPI-virtualised rectangles while the
    taskbar is reported in physical pixels, and a 192-DPI monitor comes back
    silently half-size.
    """
    import ctypes  # noqa: PLC0415

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            logger.debug("Could not set DPI awareness; sizes may be virtualised")


def enumerate_monitors() -> tuple[tuple[Monitor, str], ...]:
    """Every attached monitor, with its bounds, work area and device name."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    become_dpi_aware()

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    found: list[tuple[Monitor, str]] = []

    def callback(handle, _hdc, _rect, _param) -> int:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            found.append(
                (
                    Monitor(
                        bounds=_rect_of(info.rcMonitor),
                        work=_rect_of(info.rcWork),
                        primary=bool(info.dwFlags & _PRIMARY_FLAG),
                    ),
                    info.szDevice,
                )
            )
        return True

    proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )(callback)

    if not ctypes.windll.user32.EnumDisplayMonitors(None, None, proc, 0):
        logger.warning("EnumDisplayMonitors failed; not per-monitor")
        return ()
    return tuple(found)


def _rect_of(native) -> Rect:
    return Rect(left=native.left, top=native.top, right=native.right, bottom=native.bottom)


#: IDesktopWallpaper, and the vtable slots used. IUnknown occupies 0-2.
_CLSID_DESKTOP_WALLPAPER = "{C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD}"
_IID_DESKTOP_WALLPAPER = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"
_CLSCTX_LOCAL_SERVER = 4
_VT_RELEASE = 2
_VT_SET_WALLPAPER = 3
_VT_GET_MONITOR_DEVICE_PATH_AT = 5
_VT_GET_MONITOR_DEVICE_PATH_COUNT = 6
_VT_GET_MONITOR_RECT = 7
_VT_GET_POSITION = 11

#: DESKTOP_WALLPAPER_POSITION: one image stretched over the whole desktop.
_DWPOS_SPAN = 5

#: CoInitializeEx outcomes that mean "an apartment is available".
_S_OK = 0
_S_FALSE = 1
_RPC_E_CHANGED_MODE = -2147417850  # 0x80010106


class _DesktopWallpaper:
    """A thin ctypes shim over the IDesktopWallpaper vtable.

    Methods return HRESULTs as plain integers rather than declaring
    ``ctypes.HRESULT``, which raises on failure. Half the point of this class
    is that some calls are *expected* to fail -- ``GetMonitorRECT`` fails for
    every monitor Windows remembers but that is not plugged in right now -- and
    those reads want to be return values, not exceptions.
    """

    def __init__(self, pointer, vtable, ole32) -> None:
        self._ptr = pointer
        self._vtable = vtable
        self._ole32 = ole32

    def _method(self, slot: int, *argtypes):
        import ctypes  # noqa: PLC0415

        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(self._vtable[slot])

    def is_span(self) -> bool:
        import ctypes  # noqa: PLC0415

        position = ctypes.c_uint()
        get_position = self._method(_VT_GET_POSITION, ctypes.POINTER(ctypes.c_uint))
        if get_position(self._ptr, ctypes.byref(position)) < 0:
            return False
        return position.value == _DWPOS_SPAN

    def monitor_rects(self) -> tuple[tuple[str, Rect], ...]:
        """Every *live* monitor's wallpaper id and rectangle.

        The count includes monitors Windows merely remembers -- this machine
        reports four for two attached screens -- and GetMonitorRECT fails on
        those. Skipping them is routine, so it is not worth a warning every
        hour.
        """
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        count = ctypes.c_uint()
        get_count = self._method(_VT_GET_MONITOR_DEVICE_PATH_COUNT, ctypes.POINTER(ctypes.c_uint))
        if get_count(self._ptr, ctypes.byref(count)) < 0:
            return ()

        get_path = self._method(
            _VT_GET_MONITOR_DEVICE_PATH_AT, ctypes.c_uint, ctypes.POINTER(wintypes.LPWSTR)
        )
        get_rect = self._method(
            _VT_GET_MONITOR_RECT, wintypes.LPCWSTR, ctypes.POINTER(wintypes.RECT)
        )

        live: list[tuple[str, Rect]] = []
        for index in range(count.value):
            buffer = wintypes.LPWSTR()
            if get_path(self._ptr, index, ctypes.byref(buffer)) < 0 or not buffer.value:
                continue
            try:
                wallpaper_id = buffer.value
                rect = wintypes.RECT()
                if get_rect(self._ptr, wallpaper_id, ctypes.byref(rect)) < 0:
                    continue  # remembered but not attached
                live.append((wallpaper_id, _rect_of(rect)))
            finally:
                self._ole32.CoTaskMemFree(buffer)
        return tuple(live)

    def set_wallpaper(self, wallpaper_id: str, path: Path) -> bool:
        from ctypes import wintypes  # noqa: PLC0415

        setter = self._method(_VT_SET_WALLPAPER, wintypes.LPCWSTR, wintypes.LPCWSTR)
        return setter(self._ptr, wallpaper_id, str(path.resolve())) >= 0

    def release(self) -> None:
        import ctypes  # noqa: PLC0415

        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(self._vtable[_VT_RELEASE])(self._ptr)


@contextmanager
def _desktop_wallpaper():
    """Create the shell's wallpaper object, releasing it on the way out.

    Opened and closed around each use rather than held across a download and
    several ImageMagick passes: an hourly task that leaks a COM reference leaks
    it forever.
    """
    import ctypes  # noqa: PLC0415

    ole32 = ctypes.windll.ole32
    initialised = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    # S_FALSE means already initialised on this thread, which is fine.
    # RPC_E_CHANGED_MODE means someone else chose another apartment: usable,
    # but the balancing CoUninitialize is not ours to call.
    if initialised not in (_S_OK, _S_FALSE, _RPC_E_CHANGED_MODE):
        raise OSError(f"CoInitializeEx failed with 0x{initialised & 0xFFFFFFFF:08X}")

    pointer = ctypes.c_void_p()
    clsid, iid = _guid(_CLSID_DESKTOP_WALLPAPER), _guid(_IID_DESKTOP_WALLPAPER)
    created = ole32.CoCreateInstance(
        ctypes.byref(clsid),
        None,
        _CLSCTX_LOCAL_SERVER,
        ctypes.byref(iid),
        ctypes.byref(pointer),
    )
    if created < 0 or not pointer.value:
        if initialised != _RPC_E_CHANGED_MODE:
            ole32.CoUninitialize()
        raise OSError(
            f"CoCreateInstance(IDesktopWallpaper) failed with 0x{created & 0xFFFFFFFF:08X}"
        )

    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    com = _DesktopWallpaper(pointer, vtable, ole32)
    try:
        yield com
    finally:
        com.release()
        if initialised != _RPC_E_CHANGED_MODE:
            ole32.CoUninitialize()


def _guid(text: str):
    import ctypes  # noqa: PLC0415

    class GUID(ctypes.Structure):
        _fields_ = [
            ("data1", ctypes.c_ulong),
            ("data2", ctypes.c_ushort),
            ("data3", ctypes.c_ushort),
            ("data4", ctypes.c_ubyte * 8),
        ]

    guid = GUID()
    if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid)) < 0:
        raise OSError(f"not a usable GUID: {text}")
    return guid


def detect_displays() -> tuple[Display, ...]:
    """Live monitors joined to their wallpaper ids, or () if that is not possible.

    Best effort throughout: every failure returns (), and the caller renders a
    single wallpaper exactly as it always has.
    """
    try:
        enumerated = enumerate_monitors()
        if len(enumerated) < MIN_PER_MONITOR:
            return ()
        with _desktop_wallpaper() as com:
            if com.is_span():
                logger.info("Wallpaper position is Span; one image covers the whole desktop")
                return ()
            rects = com.monitor_rects()
    except OSError as exc:
        logger.warning("Could not enumerate monitors (%s); using a single wallpaper", exc)
        return ()

    return join_by_rect(enumerated, rects)


def set_per_monitor(assignments: Mapping[str, Path]) -> int:
    """Set one wallpaper per monitor. Returns how many were actually set.

    A partial result is deliberately reported rather than raised: a monitor
    unplugged between planning and applying should not undo the ones that did
    take, and the caller can decide whether the remainder needs a fallback.
    """
    done = 0
    try:
        with _desktop_wallpaper() as com:
            for wallpaper_id, path in assignments.items():
                if com.set_wallpaper(wallpaper_id, path):
                    done += 1
                else:
                    logger.warning("Windows refused the wallpaper for monitor %s", wallpaper_id)
    except OSError as exc:
        logger.warning("Could not set wallpapers per monitor (%s)", exc)
    return done
