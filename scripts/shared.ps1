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
    # Each option occupies two lines (label + help) so the repaint can rewrite
    # exactly the block it drew, without clearing the question above it.
    $lineCount = $Options.Count * 2 + 1

    # Reserve the block by printing it blank first. If the menu would run past
    # the bottom of the window the console scrolls now, before we anchor -- an
    # anchor captured before a scroll points at the wrong row afterwards, and
    # the repaint walks up the screen.
    1..$lineCount | ForEach-Object { Write-Host '' }
    $top = $Host.UI.RawUI.CursorPosition
    $top.X = 0
    $top.Y = [Math]::Max(0, $top.Y - $lineCount)

    function Write-Menu {
        param([int] $Selected)
        $Host.UI.RawUI.CursorPosition = $top
        for ($i = 0; $i -lt $Options.Count; $i++) {
            $on = ($i -eq $Selected)
            $arrow  = if ($on) { '>' } else { ' ' }
            $colour = if ($on) { 'Black' } else { 'Cyan' }
            $line   = ("  {0} {1}) {2}" -f $arrow, ($i + 1), $Options[$i].Label)
            # Pad to the window width so a shorter line fully overwrites a longer one.
            $line = $line.PadRight($Host.UI.RawUI.WindowSize.Width - 1)
            if ($on) { Write-Host $line -ForegroundColor $colour -BackgroundColor Cyan }
            else     { Write-Host $line -ForegroundColor $colour }

            $help = if ($Options[$i].Help) { "       " + $Options[$i].Help } else { '' }
            Write-Host $help.PadRight($Host.UI.RawUI.WindowSize.Width - 1) -ForegroundColor DarkGray
        }
        Write-Host "  Up/Down to move, Enter to choose, or press a number.".PadRight($Host.UI.RawUI.WindowSize.Width - 1) -ForegroundColor DarkGray
    }

    try { [Console]::CursorVisible = $false } catch { }
    try {
        while ($true) {
            Write-Menu -Selected $index
            $key = [Console]::ReadKey($true)

            switch ($key.Key) {
                'UpArrow'   { $index = ($index - 1 + $Options.Count) % $Options.Count }
                'DownArrow' { $index = ($index + 1) % $Options.Count }
                'Enter'     { return $Options[$index].Value }
                default {
                    # Digits pick directly, which keeps the old muscle memory.
                    $digit = 0
                    if ([int]::TryParse($key.KeyChar, [ref] $digit) -and
                        $digit -ge 1 -and $digit -le $Options.Count) {
                        $index = $digit - 1
                        Write-Menu -Selected $index
                        return $Options[$index].Value
                    }
                }
            }
        }
    } finally {
        try { [Console]::CursorVisible = $true } catch { }
        # Leave the cursor below the menu so later output does not overwrite it.
        $end = $Host.UI.RawUI.CursorPosition
        $end.Y = $top.Y + $lineCount
        $end.X = 0
        try { $Host.UI.RawUI.CursorPosition = $end } catch { }
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
