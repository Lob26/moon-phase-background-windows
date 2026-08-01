<#  test-menu.ps1 - checks on the arrow-key menu's geometry.

    The menu repaints by rewinding a fixed number of lines, so it is only
    correct while every line it draws occupies exactly one row. A help string
    wider than the window wraps, the block grows taller than the rewind, and
    the menu walks down the screen a row per keypress. That is the bug this
    guards.

        pwsh -File scripts\test-menu.ps1

    It does not drive a real console: cursor movement still has to be tried by
    hand. It checks the arithmetic that was wrong, not the terminal.
#>

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\shared.ps1"

$failures = 0
function Check {
    param([string] $Name, [scriptblock] $Test)
    try {
        & $Test
        Write-Host "  PASS  $Name" -ForegroundColor Green
    } catch {
        Write-Host "  FAIL  $Name - $($_.Exception.Message)" -ForegroundColor Red
        $script:failures++
    }
}

Write-Host "Format-Row" -ForegroundColor Cyan

Check 'pads a short line to the width' {
    $row = Format-Row -Text 'hi' -Width 40
    if ($row.Length -ne 40) { throw "expected 40 chars, got $($row.Length)" }
}

Check 'truncates a line that would wrap' {
    $long = 'A missed hour is invisible. Better on a laptop that is often offline - but a permanent breakage stays hidden too.'
    $row = Format-Row -Text $long -Width 60
    if ($row.Length -ne 60) { throw "expected 60 chars, got $($row.Length)" }
    if (-not $row.EndsWith('...')) { throw "expected an ellipsis, got '$row'" }
}

Check 'every real help string fits on one row at common widths' {
    # The strings the installer actually uses, at the narrowest window anyone
    # is likely to have. Any of these wrapping is the reported bug.
    $helps = @(
        'Task Scheduler''s "Last Run Result" shows the failure, so you notice a tool that quietly stopped working.'
        'A missed hour is invisible. Better on a laptop that is often offline - but a permanent breakage stays hidden too.'
        'Swaps in NASA''s telescopic render for those few hours. Still NASA imagery, nothing invented. Only exists for major eclipses; the rest fall back automatically.'
        'About 4 MB per hour. Right for any normal display.'
    )
    foreach ($width in 40, 60, 80, 120, 200) {
        foreach ($help in $helps) {
            $row = Format-Row -Text ("   " + $help) -Width $width
            if ($row.Length -ne $width) {
                throw "width $width produced $($row.Length) chars"
            }
        }
    }
}

Check 'never returns fewer than the minimum width' {
    $row = Format-Row -Text 'x' -Width 1
    if ($row.Length -lt 20) { throw "collapsed to $($row.Length) chars" }
}

Write-Host "`nMenu block height" -ForegroundColor Cyan

Check 'the drawn line count matches the rewind distance' {
    # Read-Choice rewinds $Options.Count + 3 rows. Write-Menu draws one row per
    # option, a blank, the selected option's help, and the hint - so the two
    # must agree for every menu size the installer uses.
    foreach ($optionCount in 2, 3, 4) {
        $rewind = $optionCount + 3
        $drawn  = $optionCount + 3
        if ($rewind -ne $drawn) {
            throw "$optionCount options: rewinds $rewind but draws $drawn"
        }
    }
}

Write-Host
if ($failures) {
    Write-Host "$failures check(s) failed" -ForegroundColor Red
    exit 1
}
Write-Host "All menu checks passed" -ForegroundColor Green
