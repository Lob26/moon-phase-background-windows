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

function Read-Choice {
    <#  A numbered menu. Returns the chosen value.
        $Options is an array of hashtables: @{ Value; Label; Help }  #>
    param(
        [string] $Question,
        [string] $Detail,
        [array]  $Options,
        [string] $Default
    )

    $values = $Options | ForEach-Object { $_.Value }
    $defaultIndex = [Math]::Max(0, [Array]::IndexOf($values, $Default))

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
