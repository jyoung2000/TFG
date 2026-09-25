# local-build.ps1
# All-in-one local build script for creating the LTX Desktop installer.
# Prepares the Python environment, installs pnpm deps, builds the frontend,
# then packages with electron-builder via create-installer.ps1.

param(
    [switch]$SkipPython,
    [switch]$Clean,
    [switch]$Unpack,
    [string]$Publish = "",
    # Optional electron-builder config override, e.g. electron-builder-wangp.yml
    # for the WanGP-identity build (own name/icons, installs side by side).
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$PythonEmbedDir = Join-Path $ProjectDir "python-embed"
$ReleaseDir = Join-Path $ProjectDir "release"

Write-Host @"

  _   _______  __  ____            _    _
 | | |_   _\ \/ / |  _ \  ___  ___| | _| |_ ___  _ __
 | |   | |  \  /  | | | |/ _ \/ __| |/ / __/ _ \| '_ \
 | |___| |  /  \  | |_| |  __/\__ \   <| || (_) | |_) |
 |_____|_| /_/\_\ |____/ \___||___/_|\_\\__\___/| .__/
                                                 |_|
  Local Build Script

"@ -ForegroundColor Cyan

Set-Location $ProjectDir

Write-Host "[0/4] Ensuring Wan2GP checkout..." -ForegroundColor Yellow
$global:LASTEXITCODE = 0
& "$ScriptDir\ensure-wan2gp.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to prepare Wan2GP checkout!" -ForegroundColor Red
    exit 1
}

# ============================================================
# Step 0: Clean if requested
# ============================================================
if ($Clean) {
    Write-Host "Cleaning previous build artifacts..." -ForegroundColor Yellow

    if (Test-Path $PythonEmbedDir) {
        Remove-Item -Recurse -Force $PythonEmbedDir
    }
    if (Test-Path $ReleaseDir) {
        Remove-Item -Recurse -Force $ReleaseDir
    }
    if (Test-Path "dist") {
        Remove-Item -Recurse -Force "dist"
    }
    if (Test-Path "dist-electron") {
        Remove-Item -Recurse -Force "dist-electron"
    }

    Write-Host "Clean complete." -ForegroundColor Green
}

# ============================================================
# Step 1: Prepare Python environment
# ============================================================
if (-not $SkipPython) {
    Write-Host "`n[1/3] Preparing Python environment..." -ForegroundColor Yellow

    if (Test-Path $PythonEmbedDir) {
        Write-Host "Python environment already exists. Use -Clean to rebuild." -ForegroundColor DarkYellow
    } else {
        & "$ScriptDir\prepare-python.ps1"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Failed to prepare Python environment!" -ForegroundColor Red
            exit 1
        }
    }
} else {
    Write-Host "`n[1/3] Skipping Python preparation (using existing)..." -ForegroundColor DarkYellow
}

if (-not (Test-Path $PythonEmbedDir)) {
    Write-Host "ERROR: Python environment not found at $PythonEmbedDir" -ForegroundColor Red
    Write-Host "Run without -SkipPython to create it." -ForegroundColor Red
    exit 1
}

# ============================================================
# Step 2: Install pnpm dependencies
# ============================================================
Write-Host "`n[2/3] Installing pnpm dependencies..." -ForegroundColor Yellow
pnpm install
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to install pnpm dependencies!" -ForegroundColor Red
    exit 1
}

# ============================================================
# Step 3: Build frontend
# ============================================================
Write-Host "`n[3/3] Building frontend and Electron app..." -ForegroundColor Yellow

# Set WanGP branding if using the WanGP config
if ($Config -like "*wangp*") {
    $env:VITE_APP_BRAND = "wangp"
    Write-Host "Setting VITE_APP_BRAND=wangp for WanGP build" -ForegroundColor Cyan
}

pnpm run build:frontend
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to build frontend!" -ForegroundColor Red
    exit 1
}

# ============================================================
# Step 4: Create installer
# ============================================================
$pkgParams = @{}
if ($Unpack)         { $pkgParams["Unpack"] = $true }
if ($Publish -ne "") { $pkgParams["Publish"] = $Publish }
if ($Config -ne "")  { $pkgParams["Config"] = $Config }

& "$ScriptDir\create-installer.ps1" @pkgParams
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
