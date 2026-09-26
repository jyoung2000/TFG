# Create/refresh the vision sidecar environment (backend/.venv-vision) and
# print how to start it. Idempotent. Requires `uv` on PATH (setup-dev installs it).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$venv = Join-Path $backend ".venv-vision"
Push-Location $backend
try {
    if (-not (Test-Path $venv)) {
        uv venv $venv --python 3.12 2>&1 | Select-Object -Last 5
    }
    $py = Join-Path $venv "Scripts\python.exe"
    uv pip install --python $py -r vision-requirements.txt 2>&1 | Select-Object -Last 10
    if ($env:TFG_VISION_CUDA -eq "1") {
        uv pip install --python $py --index-url https://download.pytorch.org/whl/cu128 torch 2>&1 | Select-Object -Last 5
    }
    Write-Host ""
    Write-Host "Vision worker ready. Start it with:"
    Write-Host "  $py $backend\vision_worker.py --port 8765"
    Write-Host "then run the app with TFG_VISION_URL=http://127.0.0.1:8765"
} finally {
    Pop-Location
}
