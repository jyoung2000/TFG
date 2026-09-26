<#
.SYNOPSIS
  Repair a Docker Desktop (Windows) start-up crash loop caused by stale
  AF_UNIX socket files — without a factory reset.

.DESCRIPTION
  Docker Desktop 4.77–4.90 on Windows can fail to start after an unclean exit
  with errors such as:
    starting services: initializing Ingest server: listening on
    unix://C:/Users/<you>/AppData/Local/Docker/run/sailor-ingest.sock:
    rename ...sailor-ingest.sock ...sailor-ingest.sock.stale:
    The file cannot be accessed by the system.
  The 0-byte socket reparse points are held by the kernel; the file itself
  cannot be renamed until reboot, but the *directory* can be moved aside and
  Docker recreates it. Nothing under the WSL distros (images, volumes,
  containers) is touched. Known issue: docker/for-win#15063,
  docker/desktop-feedback#676 / #692 / #460 / #554.

.USAGE
  powershell -ExecutionPolicy Bypass -File scripts\docker-desktop-repair.ps1
  (a factory reset is never needed for this failure; try this first)
#>
[CmdletBinding()]
param(
  [switch]$NoRestart
)
$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

Write-Host "Stopping Docker Desktop processes..."
foreach ($name in @('Docker Desktop', 'com.docker.backend', 'com.docker.build', 'com.docker.dev-envs', 'docker-secrets-engine', 'vpnkit')) {
  Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
    try { $_ | Stop-Process -Force -ErrorAction Stop; Write-Host "  stopped $($_.ProcessName) ($($_.Id))" } catch { Write-Warning "  could not stop $($_.ProcessName): $_" }
  }
}
Start-Sleep -Seconds 2

$moved = @()
$failed = @()
foreach ($dir in @(
  (Join-Path $env:LOCALAPPDATA 'Docker\run'),
  (Join-Path $env:LOCALAPPDATA 'docker-secrets-engine')
)) {
  if (-not (Test-Path $dir)) { continue }
  $target = "$dir.stale-$stamp"
  try {
    Move-Item -LiteralPath $dir -Destination $target -ErrorAction Stop
    $moved += $target
    Write-Host "Moved $dir -> $target"
  } catch {
    $failed += $dir
    Write-Warning "Could not move $dir ($_). A reboot releases the kernel handle; run this script again afterwards."
  }
}

if ($failed.Count -eq 0 -and -not $NoRestart) {
  $exe = Join-Path ${env:ProgramFiles} 'Docker\Docker\Docker Desktop.exe'
  if (Test-Path $exe) {
    Write-Host "Starting Docker Desktop..."
    Start-Process -FilePath $exe
    Write-Host "Wait for the whale to settle, then: docker info"
  } else {
    Write-Host "Docker Desktop.exe not found at $exe — start it from the Start menu."
  }
}
if ($moved.Count -gt 0) {
  Write-Host "Once Docker runs again the moved folders can be deleted:"
  $moved | ForEach-Object { Write-Host "  Remove-Item -Recurse -Force '$_'" }
}
if ($failed.Count -gt 0) { exit 2 }
