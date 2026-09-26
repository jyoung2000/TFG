<#
.SYNOPSIS
  Start the TFG backend headless (no Electron) — for agents (Hermes, MCP clients), servers and tests.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1                 # http://127.0.0.1:8000, no token on loopback
  $env:LTX_AUTH_TOKEN='secret'; .\scripts\start-backend.ps1                        # require a bearer token (also for /mcp)
  $env:LTX_PORT=8010; $env:WANGP_ROOT='D:\Wan2GP'; .\scripts\start-backend.ps1
  WanGP is found at .\Wan2GP (from scripts\ensure-wan2gp.ps1 or pnpm setup:dev:win) or via WANGP_ROOT.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = if ($env:LTX_BACKEND_PYTHON) { $env:LTX_BACKEND_PYTHON } else { Join-Path $root 'backend\.venv\Scripts\python.exe' }
if (-not (Test-Path $py)) { Write-Error "backend venv missing ($py). Run: pnpm setup:dev:win"; exit 2 }
if (-not $env:LTX_APP_DATA_DIR) { $env:LTX_APP_DATA_DIR = Join-Path $env:LOCALAPPDATA 'tfg' }
if (-not $env:LTX_PORT) { $env:LTX_PORT = '8000' }
if (-not $env:LTX_AUTH_TOKEN) { $env:LTX_OPEN_API = '1' }
if (-not $env:WANGP_ROOT -and (Test-Path (Join-Path $root 'Wan2GP\wgp.py'))) { $env:WANGP_ROOT = Join-Path $root 'Wan2GP' }
New-Item -ItemType Directory -Force -Path $env:LTX_APP_DATA_DIR | Out-Null
$wangp = if ($env:WANGP_ROOT) { $env:WANGP_ROOT } else { 'not found → API/LTX pipeline mode' }
$auth = if ($env:LTX_AUTH_TOKEN) { 'token' } else { 'open on loopback' }
Write-Host "TFG backend → http://127.0.0.1:$($env:LTX_PORT)  (data: $($env:LTX_APP_DATA_DIR); WanGP: $wangp; auth: $auth)"
Write-Host "MCP: TFG_BACKEND_URL=http://127.0.0.1:$($env:LTX_PORT) $py $root\backend\tfg_mcp.py   |   POST http://127.0.0.1:$($env:LTX_PORT)/mcp"
Set-Location (Join-Path $root 'backend')
& $py ltx2_server.py
exit $LASTEXITCODE
