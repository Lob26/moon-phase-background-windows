<#  setup_environment.ps1

    Interactive installer. Detects what it can, asks about what it cannot
    guess, writes the answers to moonback.toml, registers the hourly
    "MoonlightSonata" task and runs it once.

    Idempotent: re-running it re-asks the questions, showing your current
    answers as the defaults.

    Unattended (CI, reinstall scripts) - every question has a parameter, and
    -Unattended accepts the defaults for anything not passed:

        .\setup_environment.ps1 -Unattended
        .\setup_environment.ps1 -Unattended -SizeProfile large -OnError quiet `
            -LocationName Bogota -Latitude 4.71 -Longitude -74.07
#>

[CmdletBinding()]
param(
    [switch] $Unattended,
    # Not -Profile: $Profile is an automatic variable in Windows PowerShell.
    [ValidateSet('standard', 'large')] [string] $SizeProfile,
    [ValidateSet('report', 'quiet')]   [string] $OnError,
    [ValidateSet('bottom-right', 'bottom-left', 'top-right', 'top-left')]
    [string] $CaptionCorner,
    [bool] $EclipseImagery,
    [string] $MagickPath,
    [string] $LocationName,
    [double] $Latitude,
    [double] $Longitude,
    [switch] $NoLocation
)

$ErrorActionPreference = 'Stop'

$ascii = @'
 ****     ****   *******     *******   ****     **       ******     ********
/**/**   **/**  **/////**   **/////** /**/**   /**      /*////**   **//////**
/**//** ** /** **     //** **     //**/**//**  /**      /*   /**  **      //
/** //***  /**/**      /**/**      /**/** //** /**      /******  /**
/**  //*   /**/**      /**/**      /**/**  //**/**      /*//// **/**    *****
/**   /    /**//**     ** //**     ** /**   //****      /*    /**//**  ////**
/**        /** //*******   //*******  /**    //***      /*******  //********
//         //   ///////     ///////   //      ///       ///////    ////////
'@
Write-Host $ascii -ForegroundColor Cyan
Write-Host "By: Pedro Lobato" -ForegroundColor DarkYellow
Write-Host

$repo         = $PSScriptRoot
$taskName     = 'MoonlightSonata'
$settingsPath = Join-Path $repo 'moonback.toml'

# --------- Helpers ----------------------------------------------------
function Get-OrDefault {
    # Windows PowerShell 5.1 has no ?? operator.
    param($Value, $Fallback)
    if ([string]::IsNullOrWhiteSpace([string] $Value)) { return $Fallback }
    return $Value
}

function Read-Choice {
    <#  A numbered menu. Returns the chosen value.
        $Options is an array of hashtables: @{ Value; Label; Help }  #>
    param(
        [string] $Question,
        [string] $Detail,
        [array]  $Options,
        [string] $Default
    )

    $defaultIndex = [Math]::Max(0, [Array]::IndexOf(($Options | ForEach-Object { $_.Value }), $Default))

    if ($script:NonInteractive) { return $Options[$defaultIndex].Value }

    Write-Host
    Write-Host $Question -ForegroundColor White
    if ($Detail) { Write-Host $Detail -ForegroundColor DarkGray }
    Write-Host

    for ($i = 0; $i -lt $Options.Count; $i++) {
        $marker = if ($i -eq $defaultIndex) { '*' } else { ' ' }
        Write-Host ("  {0}{1}) {2}" -f $marker, ($i + 1), $Options[$i].Label) -ForegroundColor Cyan
        if ($Options[$i].Help) {
            Write-Host ("       {0}" -f $Options[$i].Help) -ForegroundColor DarkGray
        }
    }
    Write-Host

    while ($true) {
        $answer = Read-Host ("Choose 1-{0} [default {1}]" -f $Options.Count, ($defaultIndex + 1))
        if ([string]::IsNullOrWhiteSpace($answer)) { return $Options[$defaultIndex].Value }
        $parsed = 0
        if ([int]::TryParse($answer, [ref] $parsed) -and $parsed -ge 1 -and $parsed -le $Options.Count) {
            return $Options[$parsed - 1].Value
        }
        Write-Host "  Please enter a number between 1 and $($Options.Count)." -ForegroundColor Yellow
    }
}

function Read-Text {
    param([string] $Question, [string] $Default)
    if ($script:NonInteractive) { return $Default }
    $suffix = if ($Default) { " [$Default]" } else { '' }
    $answer = Read-Host ("{0}{1}" -f $Question, $suffix)
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim()
}

function Read-Number {
    param([string] $Question, [double] $Default, [double] $Min, [double] $Max)
    while ($true) {
        $answer = Read-Text -Question $Question -Default ([string] $Default)
        $parsed = 0.0
        if ([double]::TryParse($answer, [Globalization.NumberStyles]::Float,
                               [Globalization.CultureInfo]::InvariantCulture, [ref] $parsed)) {
            if ($parsed -ge $Min -and $parsed -le $Max) { return $parsed }
            Write-Host "  Must be between $Min and $Max." -ForegroundColor Yellow
        } else {
            Write-Host "  That is not a number. Use a decimal point, e.g. 4.71" -ForegroundColor Yellow
        }
        if ($script:NonInteractive) { throw "Invalid default for '$Question'" }
    }
}

function Read-ExistingSettings {
    <#  Previous answers become this run's defaults. A deliberately small
        TOML reader - we only ever read what this script wrote.  #>
    param([string] $Path)
    $found = @{}
    if (-not (Test-Path $Path)) { return $found }
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*([a-z_]+)\s*=\s*"?([^"#]*?)"?\s*(#.*)?$') {
            $found[$Matches[1]] = $Matches[2].Trim()
        }
    }
    return $found
}

$script:NonInteractive = $Unattended.IsPresent
$existing = Read-ExistingSettings -Path $settingsPath
if ($existing.Count -and -not $Unattended) {
    Write-Host "Found an existing moonback.toml - your current answers are the defaults." -ForegroundColor DarkGray
}

# --------- Prerequisite: uv -------------------------------------------
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv is not installed. Install it with:" -ForegroundColor Red
    Write-Host '  winget install --id=astral-sh.uv -e' -ForegroundColor Yellow
    Write-Host "then reopen this shell and run setup again."
    exit 1
}

# --------- Prerequisite: ImageMagick ----------------------------------
# Detect first, ask second: nobody should have to type a path we can find.
$magick = $null
if ($MagickPath) {
    $magick = $MagickPath
} elseif ($found = Get-Command magick -ErrorAction SilentlyContinue) {
    $magick = $found.Source
    Write-Host "Found ImageMagick on PATH: $magick" -ForegroundColor Green
} else {
    $guesses = @(
        (Get-ChildItem 'C:\Program Files\ImageMagick-*\magick.exe' -ErrorAction SilentlyContinue)
        (Get-ChildItem "$env:LOCALAPPDATA\Programs\ImageMagick-*\magick.exe" -ErrorAction SilentlyContinue)
    ) | Where-Object { $_ } | Select-Object -First 1

    if ($guesses) {
        $magick = $guesses.FullName
        Write-Host "ImageMagick is not on PATH, but it is installed here:" -ForegroundColor Yellow
        Write-Host "  $magick" -ForegroundColor Yellow
        Write-Host "Recording that path in moonback.toml so the scheduled task can find it."
    } else {
        Write-Host "ImageMagick was not found." -ForegroundColor Red
        Write-Host "  It composites the Moon onto the star field - nothing works without it."
        Write-Host "  Install it with:  winget install --id=ImageMagick.ImageMagick -e" -ForegroundColor Yellow
        $magick = Read-Text -Question "Full path to magick.exe (or blank to abort)" -Default ''
        if (-not $magick) { exit 1 }
    }
}

if (-not (Test-Path $magick) -and -not (Get-Command $magick -ErrorAction SilentlyContinue)) {
    Write-Host "'$magick' does not exist. Aborting." -ForegroundColor Red
    exit 1
}

# --------- Question: what to do when an hourly run fails --------------
$onErrorChoice = if ($OnError) { $OnError } else {
    Read-Choice -Question "When an hourly update fails, what should happen?" `
        -Detail ("Failures happen: the laptop is offline, NASA is down, ImageMagick errors.`n" +
                 "Either way the reason is always written to mbg.log.") `
        -Default (Get-OrDefault $existing['on_error'] 'report') `
        -Options @(
            @{ Value = 'report'
               Label = 'Tell me something went wrong'
               Help  = 'Task Scheduler''s "Last Run Result" shows the failure, so you notice a tool that quietly stopped working.' }
            @{ Value = 'quiet'
               Label = 'Keep the last wallpaper and say nothing'
               Help  = 'A missed hour is invisible. Better on a laptop that is often offline - but a permanent breakage stays hidden too.' }
        )
}

# --------- Question: render size ---------------------------------------
$profileChoice = if ($SizeProfile) { $SizeProfile } else {
    Read-Choice -Question "Which wallpaper size?" `
        -Detail "Both come from the same NASA render; 'large' just downloads more pixels." `
        -Default (Get-OrDefault $existing['profile'] 'standard') `
        -Options @(
            @{ Value = 'standard'; Label = 'Standard - 5461x3640 canvas'; Help = 'About 4 MB per hour. Right for any normal display.' }
            @{ Value = 'large';    Label = 'Large - 8192x5461 canvas';    Help = 'About 9 MB per hour. For very high-DPI or multi-monitor spans.' }
        )
}

# --------- Question: which corner for the text -------------------------
# The taskbar is detected at run time and the text is pushed clear of it
# automatically; this only picks which corner to start from.
$taskbarEdge = 'unknown'
try {
    $abd = Add-Type -PassThru -Namespace MB -Name Bar -MemberDefinition @'
[DllImport("shell32.dll")] public static extern IntPtr SHAppBarMessage(uint m, ref APPBARDATA d);
[StructLayout(LayoutKind.Sequential)] public struct APPBARDATA {
  public uint cbSize; public IntPtr hWnd; public uint uCallbackMessage;
  public uint uEdge; public RECT rc; public IntPtr lParam; }
[StructLayout(LayoutKind.Sequential)] public struct RECT {
  public int left, top, right, bottom; }
'@ -ErrorAction Stop
    $d = New-Object MB.Bar+APPBARDATA
    $d.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($d)
    if ([MB.Bar]::SHAppBarMessage(5, [ref] $d) -ne [IntPtr]::Zero) {
        $taskbarEdge = @('left', 'top', 'right', 'bottom')[$d.uEdge]
        $thick = if ($taskbarEdge -in 'top', 'bottom') { $d.rc.bottom - $d.rc.top }
                 else { $d.rc.right - $d.rc.left }
        Write-Host "Taskbar detected on the $taskbarEdge, $thick px thick." -ForegroundColor DarkGray
    }
} catch {
    Write-Host "Could not read the taskbar position; the text will use plain margins." -ForegroundColor DarkGray
}

$cornerChoice = if ($CaptionCorner) { $CaptionCorner } else {
    Read-Choice -Question "Which corner should the text sit in?" `
        -Detail "Whichever you pick, it is pushed clear of the taskbar automatically." `
        -Default (Get-OrDefault $existing['caption_corner'] 'bottom-right') `
        -Options @(
            @{ Value = 'bottom-right'; Label = 'Bottom right'; Help = 'The classic spot, and where desktop icons usually are not.' }
            @{ Value = 'bottom-left';  Label = 'Bottom left';  Help = 'Good if your taskbar is docked on the right.' }
            @{ Value = 'top-right';    Label = 'Top right';    Help = 'Clear of a bottom taskbar entirely.' }
            @{ Value = 'top-left';     Label = 'Top left';     Help = 'Usually where desktop icons live - they may overlap.' }
        )
}

# --------- Question: eclipse imagery -----------------------------------
# The year-long Dial-A-Moon render models phase and libration only, so it
# stays grey through totality. NASA publishes a separate telescopic sequence
# for major eclipses that does show the red Moon - real imagery, not synthetic.
$eclipseImagery = if ($PSBoundParameters.ContainsKey('EclipseImagery')) {
    if ($EclipseImagery) { 'true' } else { 'false' }
} else {
    Read-Choice -Question "During a lunar eclipse, show NASA's eclipse imagery?" `
        -Detail ("The picture used the rest of the year models the Moon's phase, not Earth's`n" +
                 "shadow, so it stays grey right through totality. NASA renders a separate`n" +
                 "telescopic sequence for major eclipses that shows the real coppery-red Moon.") `
        -Default (Get-OrDefault $existing['eclipse_imagery'] 'true') `
        -Options @(
            @{ Value = 'true'
               Label = 'Yes - show the eclipse as it looks'
               Help  = 'Swaps in NASA''s telescopic render for those few hours. Still NASA imagery, nothing invented. Only exists for major eclipses; the rest fall back automatically.' }
            @{ Value = 'false'
               Label = 'No - keep the same view all year'
               Help  = 'Every hour comes from one consistent sequence. Eclipses are still named in the caption, the Moon just stays grey.' }
        )
}

# --------- Question: where you are (for eclipse visibility) ------------
# NASA's frames never show an eclipse, so the caption is the only signal.
# Knowing where you are turns "there is an eclipse" into "you can see it".
$useLocation = -not $NoLocation
if ($LocationName) { $useLocation = $true }

if ($useLocation -and -not $LocationName) {
    $useLocation = (Read-Choice -Question "Announce lunar eclipses that are visible from where you are?" `
        -Detail ("NASA's imagery never shows an eclipse, so without this you would sit through one`n" +
                 "and never know. With a location, the wallpaper only shouts when the Moon is`n" +
                 "actually above your horizon at the time.") `
        -Default 'yes' `
        -Options @(
            @{ Value = 'yes'; Label = 'Yes - tell me when I can go outside and look'; Help = 'Needs a rough latitude and longitude. City-level precision is plenty.' }
            @{ Value = 'no';  Label = 'No - just the phase and eclipse type';          Help = 'No location stored. Eclipses are still captioned, without the visibility line.' }
        )) -eq 'yes'
}

$place = $null
if ($useLocation) {
    if ($LocationName) {
        $place = @{ name = $LocationName; latitude = $Latitude; longitude = $Longitude }
    } else {
        Write-Host
        Write-Host "Look up your coordinates at https://www.latlong.net if you are not sure." -ForegroundColor DarkGray
        Write-Host "South is a negative latitude; west is a negative longitude." -ForegroundColor DarkGray
        $place = @{
            name      = Read-Text   -Question "City or place name (shown on the wallpaper)" `
                                    -Default (Get-OrDefault $existing['name'] 'Bogota')
            latitude  = Read-Number -Question "Latitude"  -Min -90  -Max 90 `
                                    -Default ([double] (Get-OrDefault $existing['latitude'] 4.71))
            longitude = Read-Number -Question "Longitude" -Min -180 -Max 180 `
                                    -Default ([double] (Get-OrDefault $existing['longitude'] -74.07))
        }
    }
}

# --------- Write moonback.toml -----------------------------------------
$inv = [Globalization.CultureInfo]::InvariantCulture
$lines = @(
    "# Written by setup_environment.ps1. Re-run it to change these answers,",
    "# or edit by hand. Environment variables (MOONBACK_*) override anything here.",
    "",
    ("profile        = `"{0}`"" -f $profileChoice),
    ("on_error       = `"{0}`"" -f $onErrorChoice),
    ("caption_corner = `"{0}`"" -f $cornerChoice),
    ("eclipse_imagery = {0}"    -f $eclipseImagery),
    ("magick         = `"{0}`"" -f $magick.Replace('\', '\\'))
)
if ($place) {
    $lines += @(
        "",
        "# Used only to decide whether a lunar eclipse is above your horizon.",
        "[location]",
        ("name      = `"{0}`"" -f $place.name),
        ("latitude  = {0}"    -f $place.latitude.ToString($inv)),
        ("longitude = {0}"    -f $place.longitude.ToString($inv))
    )
}
# WriteAllText with an explicit no-BOM encoder: Set-Content -Encoding UTF8 on
# Windows PowerShell 5.1 emits a BOM, and a BOM is not valid TOML.
[IO.File]::WriteAllText($settingsPath, ($lines -join "`r`n") + "`r`n",
                        (New-Object Text.UTF8Encoding $false))
Write-Host
Write-Host "Wrote $settingsPath" -ForegroundColor Green

# --------- Dependencies -------------------------------------------------
& uv sync --project $repo
Write-Host "Dependencies installed" -ForegroundColor Green

$pythonw = Join-Path $repo '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "uv sync did not produce $pythonw" }

# --------- Task XML -----------------------------------------------------
# Start at the next whole hour: NASA publishes one frame per hour, so there is
# nothing new to fetch between them. No EndBoundary, so the task never expires.
$start = (Get-Date).Date.AddHours((Get-Date).Hour + 1).ToString('yyyy-MM-ddTHH:mm:ss')
$xmlTemp = [IO.Path]::Combine($env:TEMP, "$taskName.xml")

(Get-Content "$repo\wtask.template.xml" -Raw -Encoding Unicode) `
  -replace '@@PYTHON@@',  [Security.SecurityElement]::Escape($pythonw) `
  -replace '@@WORKDIR@@', [Security.SecurityElement]::Escape($repo) `
  -replace '@@START@@',   $start `
| Set-Content -Encoding Unicode -Path $xmlTemp

# --------- Register -----------------------------------------------------
# Unregister-ScheduledTask rather than `schtasks /delete ... 2>$null`: under
# $ErrorActionPreference='Stop', redirecting a native command's stderr in
# PowerShell 5.1 raises NativeCommandError even on success.
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop | Out-Null
    Write-Host "Removed the previous '$taskName' task"
} catch {
    # Not registered yet - the normal path on a first install.
}

schtasks /create /tn $taskName /xml "$xmlTemp" /f
if ($LASTEXITCODE -ne 0) { throw "schtasks failed to register $taskName" }
Write-Host "Task '$taskName' registered, first run at $start" -ForegroundColor Green

Remove-Item $xmlTemp -Force

# --------- Run once now --------------------------------------------------
Write-Host "Running once now..." -ForegroundColor Cyan
& uv run --project $repo moonback
if ($LASTEXITCODE -ne 0) {
    Write-Host "The first run failed - see $repo\mbg.log" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host
Write-Host "Setup complete - thanks!" -ForegroundColor Cyan
if ($place) {
    Write-Host ("Eclipse alerts are on for {0}." -f $place.name) -ForegroundColor DarkGray
}
