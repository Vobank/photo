<#
.SYNOPSIS
    Installs or repairs Photo on Windows. Safe to re-run at any time.

.DESCRIPTION
    Double-click install.cmd, or run from PowerShell:
        powershell -ExecutionPolicy Bypass -File install.ps1

    Everything is installed inside this folder (runtime\, backend\.venv, engine\.venv,
    models\, data\). Nothing is added to the system PATH or the registry, apart from
    optional Desktop and Start Menu shortcuts.

.PARAMETER Models
    'recommended' (default), 'none', or a comma-separated list of model ids.

.PARAMETER SkipFrontend
    Do not build or check the web UI.

.PARAMETER NoShortcut
    Do not create Desktop / Start Menu shortcuts.
#>
[CmdletBinding()]
param(
    [string]$Models = 'recommended',
    [switch]$SkipFrontend,
    [switch]$NoShortcut
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is 10x slower with the progress bar

# ---- pinned tools -------------------------------------------------------------------
$UvVersion = '0.13.7'
$UvAsset = 'uv-x86_64-pc-windows-msvc.zip'
$UvSha256 = '0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021'
$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$UvAsset"
$MinDriverMajor = 580
$MinWindowsBuild = 18362   # Windows 10 1903

$Root = $PSScriptRoot
$Runtime = Join-Path $Root 'runtime'
$Bin = Join-Path $Runtime 'bin'
$Uv = Join-Path $Bin 'uv.exe'
$Backend = Join-Path $Root 'backend'

# Windows PowerShell 5.1 turns native stderr into terminating errors under 'Stop' when it
# is redirected, so quiet probes run with 'Continue' and are judged by their exit code.
function Invoke-Quiet([string]$Exe, [string[]]$Arguments) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments 2>$null } finally { $ErrorActionPreference = $saved }
}

function Write-Step([string]$Text) { Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "  ok  $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "  !   $Text" -ForegroundColor Yellow }

function Stop-Install([string]$Text) {
    Write-Host ''
    Write-Host "Installation stopped: $Text" -ForegroundColor Red
    exit 1
}

function Test-System {
    Write-Step 'Checking system'
    if (-not [Environment]::Is64BitOperatingSystem) {
        Stop-Install 'Photo needs 64-bit Windows.'
    }
    $build = [Environment]::OSVersion.Version.Build
    if ($build -lt $MinWindowsBuild) {
        Stop-Install "Windows 10 version 1903 or newer is required (this is build $build)."
    }
    Write-Ok "Windows build $build"

    if ($Root.Length -gt 80) {
        Write-Warn "The install folder path is long ($($Root.Length) characters). If installation fails"
        Write-Warn 'with path errors, move Photo to a shorter folder such as C:\Photo.'
    }

    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($null -eq $smi) {
        Stop-Install ('No NVIDIA driver found. Install the latest driver from ' +
            'https://www.nvidia.com/drivers and run the installer again.')
    }
    # No Select-Object -First here: stopping the pipeline early loses $LASTEXITCODE.
    $lines = @(Invoke-Quiet $smi.Source @('--query-gpu=name,driver_version', '--format=csv,noheader'))
    $code = $LASTEXITCODE
    $line = if ($lines.Count -gt 0) { [string]$lines[0] } else { '' }
    if ($code -ne 0 -or -not $line) {
        Stop-Install 'nvidia-smi could not talk to the GPU. Reinstall the NVIDIA driver and reboot.'
    }
    $name, $driver = ($line -split ',') | ForEach-Object { $_.Trim() }
    $major = 0
    [void][int]::TryParse(($driver -split '\.')[0], [ref]$major)
    if ($major -lt $MinDriverMajor) {
        Stop-Install ("NVIDIA driver $driver is too old; version $MinDriverMajor or newer is required. " +
            'Update it from https://www.nvidia.com/drivers')
    }
    Write-Ok "$name, driver $driver"
}

function Get-FileSha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Install-Uv([string]$Destination = $Bin) {
    $target = Join-Path $Destination 'uv.exe'
    if (Test-Path -LiteralPath $target) {
        $current = (Invoke-Quiet $target @('--version')) -as [string]
        if ($current -and $current.StartsWith("uv $UvVersion")) {
            Write-Ok "uv $UvVersion"
            return
        }
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("photo-uv-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $zip = Join-Path $tmp $UvAsset
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor
            [Net.SecurityProtocolType]::Tls12
        $attempt = 0
        while ($true) {
            $attempt++
            try {
                Invoke-WebRequest -Uri $UvUrl -OutFile $zip -UseBasicParsing
                break
            } catch {
                if ($attempt -ge 4) { Stop-Install "Could not download uv: $($_.Exception.Message)" }
                Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
            }
        }
        $actual = Get-FileSha256 $zip
        if ($actual -ne $UvSha256) {
            Stop-Install "uv download failed verification (got $actual). Check your connection and retry."
        }
        $unpacked = Join-Path $tmp 'x'
        Expand-Archive -LiteralPath $zip -DestinationPath $unpacked -Force
        foreach ($exe in 'uv.exe', 'uvx.exe') {
            $src = Join-Path $unpacked $exe
            if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $Destination -Force }
        }
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Ok "uv $UvVersion (verified)"
}

function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$What) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Stop-Install "$What failed (exit code $LASTEXITCODE). See the messages above." }
}

function Install-App {
    Write-Step 'Installing Photo'
    # Keep every byte uv downloads inside this folder.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Runtime 'python'
    $env:UV_CACHE_DIR = Join-Path $Runtime 'cache'
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $Backend '.venv'
    $env:PHOTO_UV = $Uv
    Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

    Invoke-Native $Uv @('sync', '--locked', '--no-dev', '--project', $Backend) 'Installing the app server'
    Write-Ok 'App server'

    $photo = Join-Path $Backend '.venv\Scripts\photo.exe'
    $setupArgs = @('setup', '--models', $Models)
    if ($SkipFrontend) { $setupArgs += '--skip-frontend' }
    Remove-Item Env:UV_PROJECT_ENVIRONMENT   # setup points uv at the engine itself
    Invoke-Native $photo $setupArgs 'Setup'
}

function New-Launcher {
    $launcher = Join-Path $Root 'Photo.cmd'
    if (Test-Path -LiteralPath $launcher) { return $launcher }
    $content = @(
        '@echo off',
        'setlocal',
        'chcp 65001 >nul',
        'set "PHOTO_EXE=%~dp0backend\.venv\Scripts\photo.exe"',
        'if not exist "%PHOTO_EXE%" (',
        '    echo Photo is not installed yet. Double-click install.cmd first.',
        '    pause',
        '    exit /b 1',
        ')',
        '"%PHOTO_EXE%" serve --open %*',
        'if errorlevel 1 pause'
    )
    [IO.File]::WriteAllLines($launcher, $content, (New-Object Text.ASCIIEncoding))
    return $launcher
}

function New-Shortcuts([string]$Launcher) {
    $shell = New-Object -ComObject WScript.Shell
    $folders = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
    foreach ($folder in $folders) {
        if (-not $folder -or -not (Test-Path -LiteralPath $folder)) { continue }
        $lnk = $shell.CreateShortcut((Join-Path $folder 'Photo.lnk'))
        $lnk.TargetPath = $Launcher
        $lnk.WorkingDirectory = $Root
        $lnk.Description = 'Photo - local AI image studio'
        $icon = Join-Path $Root 'frontend\public\favicon.ico'
        if (Test-Path -LiteralPath $icon) { $lnk.IconLocation = $icon }
        $lnk.Save()
    }
    Write-Ok 'Desktop and Start Menu shortcuts'
}

function Main {
    Write-Host "Photo installer - $Root"
    Test-System
    Write-Step 'Tools'
    Install-Uv
    Install-App
    $launcher = New-Launcher
    if (-not $NoShortcut) { New-Shortcuts $launcher }
    Write-Host ''
    Write-Host 'Photo is ready. Start it from the desktop shortcut or Photo.cmd.' -ForegroundColor Green
}

# Dot-sourcing (". .\install.ps1") loads the functions without installing, for tests.
if ($MyInvocation.InvocationName -ne '.') { Main }
