<#  Shared helpers for setup_environment.ps1 and uninstall.ps1.

    Dot-source it:  . "$PSScriptRoot\scripts\shared.ps1"

    Every prompt honours $script:NonInteractive, which the caller sets from its
    own -Unattended switch. That is what lets both scripts run headless with
    exactly the behaviour their flags describe, instead of hanging on a prompt.
#>

function Invoke-Native {
    <#  Run a native executable and fail on its exit code, not its stderr.

        Windows PowerShell 5.1 wraps a native command's stderr in ErrorRecords,
        so under $ErrorActionPreference='Stop' any tool that reports progress
        there blows up mid-run even when it succeeded. uv does exactly that,
        which broke fresh installs while cached ones passed.  #>
    param([scriptblock] $Command, [string] $What)

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # Fold stderr into the output stream and print the ErrorRecords as
        # plain text: uv's progress lines are informational, and letting them
        # render as red error blocks makes a successful install look broken.
        & $Command 2>&1 | ForEach-Object {
            if ($_ -is [Management.Automation.ErrorRecord]) {
                Write-Host "  $($_.Exception.Message)" -ForegroundColor DarkGray
            } else {
                Write-Host $_
            }
        }
    } finally { $ErrorActionPreference = $previous }

    if ($LASTEXITCODE -ne 0) { throw "$What failed with exit code $LASTEXITCODE" }
}

function Get-OrDefault {
    # Windows PowerShell 5.1 has no ?? operator.
    param($Value, $Fallback)
    if ([string]::IsNullOrWhiteSpace([string] $Value)) { return $Fallback }
    return $Value
}

function Format-Row {
    <#  Pad AND truncate a line to the console width.

        Truncating is the part that matters. A line longer than the window
        wraps onto a second row, so a menu block becomes taller than the number
        of lines the repaint rewinds -- and the menu walks down the screen, one
        row per keypress. Padding alone only fixes the opposite problem, of a
        short line failing to overwrite a longer one underneath it.  #>
    param([string] $Text, [int] $Width = 0)

    if ($Width -le 0) {
        $Width = try { $Host.UI.RawUI.WindowSize.Width - 1 } catch { 80 }
    }
    $Width = [Math]::Max(20, $Width)

    if ($Text.Length -gt $Width) { return $Text.Substring(0, $Width - 3) + '...' }
    return $Text.PadRight($Width)
}

function Test-ArrowKeysUsable {
    <#  Can we read individual keypresses and repaint?

        Not in every host: ISE and the VS Code integrated console have no
        RawUI key support, and a redirected stdin has none either. Those fall
        back to typing a number rather than hanging on a key that never comes.  #>
    if ([Console]::IsInputRedirected) { return $false }
    if ($Host.Name -notmatch 'ConsoleHost') { return $false }
    try { $null = $Host.UI.RawUI.CursorPosition; return $true } catch { return $false }
}

function Read-Choice {
    <#  A menu. Arrow keys where the host supports them, typed numbers where it
        does not. Returns the chosen value.
        $Options is an array of hashtables: @{ Value; Label; Help }  #>
    param(
        [string] $Question,
        [string] $Detail,
        [array]  $Options,
        [string] $Default
    )

    $values = $Options | ForEach-Object { $_.Value }
    $index = [Math]::Max(0, [Array]::IndexOf($values, $Default))

    if ($script:NonInteractive) { return $Options[$index].Value }

    Write-Host
    Write-Host $Question -ForegroundColor White
    if ($Detail) { Write-Host $Detail -ForegroundColor DarkGray }
    Write-Host

    if (-not (Test-ArrowKeysUsable)) {
        # --- Plain fallback: print once, read a number ---
        for ($i = 0; $i -lt $Options.Count; $i++) {
            $marker = if ($i -eq $index) { '*' } else { ' ' }
            Write-Host ("  {0}{1}) {2}" -f $marker, ($i + 1), $Options[$i].Label) -ForegroundColor Cyan
            if ($Options[$i].Help) {
                Write-Host ("       {0}" -f $Options[$i].Help) -ForegroundColor DarkGray
            }
        }
        Write-Host
        while ($true) {
            $answer = Read-Host ("Choose 1-{0} [default {1}]" -f $Options.Count, ($index + 1))
            if ([string]::IsNullOrWhiteSpace($answer)) { return $Options[$index].Value }
            $parsed = 0
            if ([int]::TryParse($answer, [ref] $parsed) -and
                $parsed -ge 1 -and $parsed -le $Options.Count) {
                return $Options[$parsed - 1].Value
            }
            Write-Host "  Please enter a number between 1 and $($Options.Count)." -ForegroundColor Yellow
        }
    }

    # --- Arrow-key menu ---
    # One line per option plus a help line for the selected one and a hint.
    # Help used to be printed under every option, which made the block twice as
    # tall for no gain -- only the selected option's help is worth reading.
    $lineCount = $Options.Count + 3

    function Write-Menu {
        param([int] $Selected)
        for ($i = 0; $i -lt $Options.Count; $i++) {
            $on = ($i -eq $Selected)
            $row = Format-Row ("  {0} {1}) {2}" -f $(if ($on) { '>' } else { ' ' }), ($i + 1), $Options[$i].Label)
            if ($on) { Write-Host $row -ForegroundColor Black -BackgroundColor Cyan }
            else     { Write-Host $row -ForegroundColor Cyan }
        }
        Write-Host (Format-Row '')
        Write-Host (Format-Row ("   " + $Options[$Selected].Help)) -ForegroundColor DarkGray
        Write-Host (Format-Row "   Up/Down to move, Enter to choose, or press a number.") -ForegroundColor DarkGray
    }

    try { [Console]::CursorVisible = $false } catch { }
    try {
        Write-Menu -Selected $index
        while ($true) {
            $key = [Console]::ReadKey($true)

            $chosen = $false
            switch ($key.Key) {
                'UpArrow'   { $index = ($index - 1 + $Options.Count) % $Options.Count }
                'DownArrow' { $index = ($index + 1) % $Options.Count }
                'Enter'     { $chosen = $true }
                default {
                    # Digits pick directly, which keeps the old muscle memory.
                    $digit = 0
                    if ([int]::TryParse($key.KeyChar, [ref] $digit) -and
                        $digit -ge 1 -and $digit -le $Options.Count) {
                        $index = $digit - 1
                        $chosen = $true
                    }
                }
            }

            # Rewind over the block just drawn and repaint it in place. The
            # anchor is measured from where the previous draw *finished*, not
            # from a position captured before it: if the console scrolled
            # mid-draw an earlier anchor is already stale, and measuring
            # afterwards is self-correcting.
            $spot = $Host.UI.RawUI.CursorPosition
            $spot.X = 0
            $spot.Y = [Math]::Max(0, $spot.Y - $lineCount)
            $Host.UI.RawUI.CursorPosition = $spot
            Write-Menu -Selected $index

            if ($chosen) { return $Options[$index].Value }
        }
    } finally {
        try { [Console]::CursorVisible = $true } catch { }
        Write-Host
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
