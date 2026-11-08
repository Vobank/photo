<#
.SYNOPSIS
    Updates Photo: pulls the latest code (git checkouts only), then re-runs the installer.
#>
[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$InstallArgs = @())

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

if (Test-Path -LiteralPath (Join-Path $Root '.git')) {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($null -eq $git) {
        Write-Host 'git is not installed; skipping code update.' -ForegroundColor Yellow
    } else {
        & $git.Source -C $Root pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Could not fast-forward (local changes?). Resolve with git, then retry.' -ForegroundColor Red
            exit 1
        }
    }
} else {
    Write-Host 'Not a git checkout: download the latest release from GitHub to update the code.'
}

& (Join-Path $Root 'install.ps1') @InstallArgs
exit $LASTEXITCODE
