# Installation

**[← Design notes](README.md) · [Installation](INSTALL.md)**

Windows 10/11. Two prerequisites, one command.

---

## 1. Prerequisites

```powershell
winget install --id=astral-sh.uv -e
winget install --id=ImageMagick.ImageMagick -e
```

Reopen your terminal afterwards so `PATH` picks both up, then check:

```powershell
uv --version
magick -version
```

If `magick` is not found but ImageMagick *is* installed, its installer skipped
the PATH entry. Either fix PATH or point the tool straight at it:

```powershell
[Environment]::SetEnvironmentVariable(
  'MOONBACK_MAGICK',
  'C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe',
  'User')
```

Set it at **User** scope, not just in your shell — the scheduled task runs in a
different environment than the terminal you tested in.

Python itself is not a prerequisite: `uv` fetches the interpreter it needs.

## 2. Install

```powershell
git clone https://github.com/pedrolobato/moon-phase-background-windows
cd moon-phase-background-windows
.\setup_environment.ps1
```

The installer detects ImageMagick, asks three questions, writes your answers to
`moonback.toml`, registers an hourly **MoonlightSonata** task starting at the
next whole hour, and runs it once so you see the result immediately.

The three questions:

| Question | Why it is asked |
|---|---|
| What should happen when an hourly update fails? | `report` surfaces failures in Task Scheduler's *Last Run Result*; `quiet` keeps the previous wallpaper and stays silent. Either way it is logged. |
| Which wallpaper size? | `standard` (~4 MB/hour) or `large` (~9 MB/hour). |
| Where are you? | Only used to decide whether a lunar eclipse is above your horizon. Skippable. |

Re-run it any time to change your answers — your current ones become the
defaults.

If PowerShell blocks the script:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_environment.ps1
```

### Unattended install

Every question has a flag, so reinstalls and CI need no human:

```powershell
.\setup_environment.ps1 -Unattended
.\setup_environment.ps1 -Unattended -SizeProfile large -OnError quiet `
    -LocationName "Bogota" -Latitude 4.71 -Longitude -74.07
.\setup_environment.ps1 -Unattended -NoLocation
```

### Run it by hand

```powershell
uv run moonback            # once, printing the caption
uv run moonback --version
```

---

## Configuration

Settings live in `moonback.toml`, written by the installer. Edit it by hand or
re-run setup. It is gitignored — the paths and coordinates in it are yours.

```toml
profile  = "standard"     # or "large"
on_error = "report"       # or "quiet"
magick   = "C:\\Program Files\\ImageMagick-7.1.2-Q16-HDRI\\magick.exe"

# Delete this section to turn eclipse visibility off.
[location]
name      = "Bogota"
latitude  = 4.71
longitude = -74.07
```

| Key | Env override | Default | Purpose |
|---|---|---|---|
| `magick` | `MOONBACK_MAGICK` | `magick` on PATH | Command name or full path to `magick.exe` |
| `profile` | `MOONBACK_PROFILE` | `standard` | `standard` (5461×3640) or `large` (8192×5461) |
| `on_error` | `MOONBACK_ON_ERROR` | `report` | `report` exits non-zero on failure; `quiet` keeps the last wallpaper and exits 0 |
| `year` | `MOONBACK_YEAR` | current UTC year | Override the ephemeris year; mostly for testing |
| `connect_timeout` | `MOONBACK_CONNECT_TIMEOUT` | `10` | Seconds to connect to NASA |
| `read_timeout` | `MOONBACK_READ_TIMEOUT` | `60` | Seconds to read the frame body |
| `attempts` | `MOONBACK_ATTEMPTS` | `4` | Total download attempts, including the first |
| `[location]` | — | none | Latitude/longitude for eclipse visibility |
| — | `MOONBACK_HOME` | the repo directory | Where `data/`, the canvases and `back.tif` live |
| — | `MOONBACK_LOG_FILE` | `<home>\mbg.log` | Log destination |

**Environment variables always win over the file**, so a one-off run needs no
edit:

```powershell
$env:MOONBACK_PROFILE = 'large'; uv run moonback
```

Anything invalid is rejected on startup with a message naming the setting, and
exits with code `2`.

### Using your own star field

`best_small.tif` (`standard`) and `best.tif` (`large`) are the canvases the Moon
is composited onto. Replace either with an image of the same dimensions and it
just works. A **different** size also needs new caption offsets in
`PROFILES` in [`moonback/config.py`](moonback/config.py) — `caption_offset` is
measured from the right edge and the vertical centre.

---

## Rolling over to a new year

NASA publishes a new visualisation every year under a new SVS id. Only that id
needs a human — the ephemeris table downloads itself on first use, so the first
hourly run after midnight on 1 January repairs itself once the id is known.

### Automatic (recommended)

The [year-rollover workflow](.github/workflows/year-rollover.yml) runs on
5 January, finds the new id, verifies it serves real frames, runs the tests and
opens a PR. **Merge the PR and you are done.** Trigger it early from the Actions
tab ("Run workflow") to test.

It needs one repo setting: *Settings → Actions → General → Workflow permissions*
→ enable **Allow GitHub Actions to create and approve pull requests**.

### Manual

If you would rather not use the workflow, or NASA has not published yet:

```powershell
uv run python scripts/rollover_year.py 2027
```

That does the same discovery and patching locally. To do it entirely by hand:

1. Find the year's "Moon Phase and Libration" page in the
   [SVS gallery](https://svs.gsfc.nasa.gov/gallery/moonphase/) and take the id
   from the URL — `https://svs.gsfc.nasa.gov/5587/` → **5587**. Take care not to
   grab the *South Up* variant, which is a different id.
2. Add it to `SVS_COLLECTIONS` in [`moonback/config.py`](moonback/config.py):

   ```python
   SVS_COLLECTIONS = {2025: 5415, 2026: 5587, 2027: <new id>}
   ```

3. Run `uv run moonback`. The ephemeris downloads and caches itself.

### Eclipses

[`data/lunar_eclipses.txt`](data/lunar_eclipses.txt) covers 2021–2040, so it
needs no annual attention. To extend it, add the next decade to `DECADES` in
`scripts/fetch_eclipses.py` and run:

```powershell
uv run python scripts/fetch_eclipses.py
```

If the file is missing or corrupt the wallpaper still updates — it just captions
without eclipse information and logs a warning.

---

## Managing the scheduled task

```powershell
schtasks /query /tn MoonlightSonata /v /fo list   # status and last result
schtasks /run   /tn MoonlightSonata               # run now
schtasks /end   /tn MoonlightSonata               # stop a run in progress
schtasks /delete /tn MoonlightSonata /f           # remove
```

The task runs hourly at `LeastPrivilege` with an `InteractiveToken`, so it needs
you logged in — which is fine, since there is no point changing a wallpaper
nobody is looking at. It has a 10-minute execution limit and does not wake the
machine.

---

## Troubleshooting

**Start with the log** — `mbg.log` in the repo directory. One run is five lines.

| What you see | What it means |
|---|---|
| `ImageMagick is required but 'magick' is not on PATH` | See [Prerequisites](#1-prerequisites); set `MOONBACK_MAGICK` at User scope |
| `No NASA visualisation is mapped for <year>` | [Roll over to the new year](#rolling-over-to-a-new-year) |
| `returned 404; the frame number or the SVS collection id ... is probably wrong` | Wrong SVS id for that year, or NASA moved the frames |
| `giving up on ... after 4 attempts` | NASA unreachable. It retried with backoff; the next hourly run will try again |
| `ephemeris row N is ... but ... was requested` | `data/mooninfo_<year>.txt` doesn't match its filename year — delete it and it will refetch |
| `Eclipse catalogue unavailable` | `data/lunar_eclipses.txt` is missing or corrupt; the wallpaper still updates, just without eclipse captions |
| `ImageMagick exited N ...` | ImageMagick's own stderr follows on the same line |
| Task runs, exit code 0, wallpaper unchanged | A wallpaper app (Wallpaper Engine, Lively) is overriding it |

Exit codes: `0` success, `1` runtime failure, `2` bad configuration.

### Uninstall

```powershell
schtasks /delete /tn MoonlightSonata /f
```

Then delete the folder. Remove `MOONBACK_*` variables if you set any.
