<#  uninstall.ps1

    Reverses setup_environment.ps1, asking before anything destructive.

    It removes what the installer created and nothing else. The repository
    itself is left alone - deleting a folder is not something a script inside
    that folder should do behind your back.

    Unattended removes only what a flag asks for, so it is never a surprise:

        .\uninstall.ps1 -Unattended                 # the task (and build caches) only
        .\uninstall.ps1 -Unattended -All            # task, settings, venv, generated files
        .\uninstall.ps1 -Unattended -RemoveSettings -RemoveGenerated

    -WhatIf lists everything it would touch and changes nothing.
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [switch] $Unattended,
    [switch] $All,
    [switch] $RemoveSettings,
    [switch] $RemoveGenerated,
    [switch] $RemoveVenv
)

$ErrorActionPreference = 'Stop'

$repo     = $PSScriptRoot
$taskName = 'MoonlightSonata'

. "$PSScriptRoot\scripts\shared.ps1"
$script:NonInteractive = $Unattended.IsPresent

if ($All) { $RemoveSettings = $RemoveGenerated = $RemoveVenv = $true }

Write-Host "Uninstalling MoonlightSonata" -ForegroundColor Cyan
Write-Host "  $repo" -ForegroundColor DarkGray
Write-Host

$removed = [Collections.Generic.List[string]]::new()
$kept    = [Collections.Generic.List[string]]::new()

function Remove-Target {
    <#  Delete a path and record what happened. Missing paths are not an
        error: uninstall has to be safe to run twice, and safe to run after a
        half-finished install.

        Advanced on purpose - $PSCmdlet only exists in an advanced function,
        and SupportsShouldProcess here is what makes -WhatIf reach the actual
        deletions rather than just the top-level steps.  #>
    [CmdletBinding(SupportsShouldProcess)]
    param([string] $Path, [string] $Label)

    if (-not (Test-Path $Path)) { return }
    if ($PSCmdlet.ShouldProcess($Path, 'Remove')) {
        try {
            Remove-Item $Path -Recurse -Force -ErrorAction Stop
            $removed.Add($Label)
        } catch {
            Write-Host "  Could not remove $Label - $($_.Exception.Message)" -ForegroundColor Yellow
            Write-Host "  (a file may be open; close it and re-run)" -ForegroundColor DarkGray
        }
    }
}

# --------- The scheduled task ------------------------------------------
# This is the part that actually matters: leave it behind and the wallpaper
# keeps changing every hour long after everything else is gone.
$task = $null
try { $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop } catch { }

if ($task) {
    if ($PSCmdlet.ShouldProcess($taskName, 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false | Out-Null
        Write-Host "Removed the hourly '$taskName' task." -ForegroundColor Green
        $removed.Add("scheduled task '$taskName'")
    }
} else {
    Write-Host "No '$taskName' task was registered." -ForegroundColor DarkGray
}

# --------- Generated files ----------------------------------------------
# Deleting back.tif does NOT blank the desktop: Windows copies the wallpaper
# into %APPDATA%\Microsoft\Windows\Themes\TranscodedWallpaper and points the
# registry at that copy, so the last Moon stays up until you pick another.
$generated = @(
    @{ Path = Join-Path $repo 'back.tif';  Label = 'back.tif (the generated wallpaper)' }
    @{ Path = Join-Path $repo 'mbg.log';   Label = 'mbg.log' }
    @{ Path = Join-Path $repo 'samples';   Label = 'samples/' }
) + @(Get-ChildItem -Path $repo -Filter 'moon.*.tif' -File -ErrorAction SilentlyContinue |
        ForEach-Object { @{ Path = $_.FullName; Label = $_.Name } }
     ) + @(Get-ChildItem -Path $repo -Filter '*.part' -File -ErrorAction SilentlyContinue |
        ForEach-Object { @{ Path = $_.FullName; Label = $_.Name } })

$presentGenerated = @($generated | Where-Object { Test-Path $_.Path })

if ($presentGenerated.Count) {
    # Unattended removes only what a flag asked for. Falling through to a
    # prompt's default would make `-Unattended` quietly destructive.
    if (-not $RemoveGenerated -and -not $script:NonInteractive) {
        $RemoveGenerated = (Read-Choice -Question "Delete the generated wallpaper and logs?" `
            -Detail ("Your desktop will keep showing the last Moon either way - Windows caches`n" +
                     "the image itself, so removing back.tif does not blank the screen.") `
            -Default 'keep' `
            -Options @(
                @{ Value = 'keep';   Label = 'Keep them';   Help = "back.tif is a 57 MB picture you may still want; mbg.log is the only record of what happened." }
                @{ Value = 'delete'; Label = 'Delete them'; Help = "Frees about $([math]::Round((($presentGenerated | ForEach-Object { (Get-Item $_.Path).Length } | Measure-Object -Sum).Sum)/1MB)) MB." }
            )) -eq 'delete'
    }
    if ($RemoveGenerated) {
        foreach ($item in $presentGenerated) { Remove-Target -Path $item.Path -Label $item.Label }
    } else {
        $kept.Add('generated wallpaper and logs')
    }
}

# --------- Settings ------------------------------------------------------
$settingsPath = Join-Path $repo 'moonback.toml'
if (Test-Path $settingsPath) {
    if (-not $RemoveSettings -and -not $script:NonInteractive) {
        $RemoveSettings = (Read-Choice -Question "Delete moonback.toml?" `
            -Detail "Your install-time answers: size, corner, failure behaviour and location." `
            -Default 'keep' `
            -Options @(
                @{ Value = 'keep';   Label = 'Keep it';   Help = 'Reinstalling later will offer these answers as the defaults.' }
                @{ Value = 'delete'; Label = 'Delete it'; Help = 'A future install starts from scratch. Also removes the stored coordinates.' }
            )) -eq 'delete'
    }
    if ($RemoveSettings) { Remove-Target -Path $settingsPath -Label 'moonback.toml' }
    else { $kept.Add('moonback.toml') }
}

# --------- Virtual environment -------------------------------------------
$venv = Join-Path $repo '.venv'
if (Test-Path $venv) {
    if (-not $RemoveVenv -and -not $script:NonInteractive) {
        $RemoveVenv = (Read-Choice -Question "Delete the .venv folder?" `
            -Detail "The Python environment uv created for this project." `
            -Default 'delete' `
            -Options @(
                @{ Value = 'delete'; Label = 'Delete it'; Help = 'Frees a few hundred MB. `uv sync` rebuilds it in seconds.' }
                @{ Value = 'keep';   Label = 'Keep it';   Help = 'Useful if you only want to stop the schedule but still run moonback by hand.' }
            )) -eq 'delete'
    }
    if ($RemoveVenv) { Remove-Target -Path $venv -Label '.venv/' }
    else { $kept.Add('.venv/') }
}

# Caches are pure build artefacts - no question needed.
foreach ($cache in '.pytest_cache', '.ruff_cache', 'moonback\__pycache__', 'tests\__pycache__') {
    Remove-Target -Path (Join-Path $repo $cache) -Label $cache
}

# --------- Environment variables -----------------------------------------
# The installer never sets these, but INSTALL.md suggests MOONBACK_MAGICK for
# awkward setups, so a leftover one would quietly affect a future install.
$leftover = @([Environment]::GetEnvironmentVariables('User').Keys |
              Where-Object { $_ -like 'MOONBACK_*' })
if ($leftover.Count) {
    Write-Host
    Write-Host "These user environment variables are still set:" -ForegroundColor Yellow
    $leftover | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    # Unattended keeps them unless -All was explicit: these can be set for
    # reasons that have nothing to do with this project, and a teardown script
    # should not silently reach outside the folder it was run from.
    $clear = if ($script:NonInteractive) { $All.IsPresent } else {
        (Read-Choice -Question "Clear them?" `
            -Detail "They would override the settings of any future install." `
            -Default 'clear' `
            -Options @(
                @{ Value = 'clear'; Label = 'Clear them' }
                @{ Value = 'keep';  Label = 'Leave them alone'; Help = 'Choose this if you set them for something else.' }
            )) -eq 'clear'
    }
    if ($clear) {
        foreach ($name in $leftover) {
            if ($PSCmdlet.ShouldProcess($name, 'Clear user environment variable')) {
                [Environment]::SetEnvironmentVariable($name, $null, 'User')
                $removed.Add("`$env:$name")
            }
        }
    } else {
        $kept.Add('MOONBACK_* environment variables')
    }
}

# --------- Report ---------------------------------------------------------
Write-Host
if ($WhatIfPreference) {
    Write-Host "Dry run - nothing above was actually removed." -ForegroundColor Cyan
} elseif ($removed.Count) {
    Write-Host "Removed:" -ForegroundColor Green
    $removed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Green }
} else {
    Write-Host "Nothing to remove - it was not installed." -ForegroundColor DarkGray
}
if ($kept.Count) {
    Write-Host "Kept:" -ForegroundColor DarkGray
    $kept | ForEach-Object { Write-Host "  - $_" -ForegroundColor DarkGray }
}

Write-Host
Write-Host "The wallpaper will stay on the last Moon until you choose another" -ForegroundColor DarkGray
Write-Host "in Settings > Personalisation > Background." -ForegroundColor DarkGray
Write-Host "Delete this folder when you are ready - nothing outside it is left." -ForegroundColor Cyan
