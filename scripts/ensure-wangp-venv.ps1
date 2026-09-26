# Create/refresh WanGP's OWN Python environment (Wan2GP/.venv). Idempotent.
#
# WanGP needs ~100 packages (gradio, pinned diffusers, onnxruntime-gpu, ...)
# that are not in backend/uv.lock. They used to be installed into the backend
# venv, where the next `uv sync` removed them ("No module named 'gradio'").
# Now WanGP gets this separate venv; the backend detects Wan2GP/.venv and runs
# WanGP from it as a worker process (backend/wangp_worker.py), so backend
# syncs and WanGP's pins can no longer break each other.
#
# Defaults are the combination proven on an RTX 4070: Python 3.12 with
# torch 2.10.0 / torchvision 0.25.0 / torchaudio 2.10.0 from the CUDA 12.8
# index (the trio WanGP's README documents). Requires `uv` on PATH.
param(
    [string]$PythonVersion = "3.12",
    [string]$TorchVersion = "2.10.0",
    [string]$TorchvisionVersion = "0.25.0",
    [string]$TorchaudioVersion = "2.10.0",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128",
    [switch]$Recreate
)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

& (Join-Path $ScriptDir "ensure-wan2gp.ps1")
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "Wan2GP checkout setup failed" }

$Wan2GPDir = Join-Path $ProjectDir "Wan2GP"
if (-not (Test-Path (Join-Path $Wan2GPDir "wgp.py"))) {
    if ($env:WANGP_ROOT -and (Test-Path (Join-Path $env:WANGP_ROOT "wgp.py"))) {
        $Wan2GPDir = $env:WANGP_ROOT
    } else {
        throw "No Wan2GP checkout found (expected $Wan2GPDir or WANGP_ROOT)."
    }
}
$Wan2GPDir = (Resolve-Path $Wan2GPDir).Path
$VenvDir = Join-Path $Wan2GPDir ".venv"
$Py = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $Wan2GPDir "requirements.txt"

if ($Recreate -and (Test-Path $VenvDir)) {
    Write-Host "Removing $VenvDir ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $VenvDir
}
if (-not (Test-Path $Py)) {
    Write-Host "Creating WanGP environment at $VenvDir (Python $PythonVersion) ..." -ForegroundColor Yellow
    uv venv $VenvDir --python $PythonVersion
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }
}

Write-Host "Installing CUDA PyTorch $TorchVersion from $TorchIndexUrl ..." -ForegroundColor Yellow
uv pip install --python $Py "torch==$TorchVersion" "torchvision==$TorchvisionVersion" "torchaudio==$TorchaudioVersion" --index-url $TorchIndexUrl
if ($LASTEXITCODE -ne 0) { throw "PyTorch install failed" }

# Pin the CUDA build so no requirement can swap it for a CPU wheel from PyPI.
$Constraints = Join-Path $env:TEMP "tfg-wangp-torch-constraints.txt"
@("torch==$TorchVersion", "torchvision==$TorchvisionVersion", "torchaudio==$TorchaudioVersion") | Set-Content -Encoding ascii $Constraints
Write-Host "Installing WanGP requirements from $Requirements ..." -ForegroundColor Yellow
uv pip install --python $Py -r $Requirements -c $Constraints
$code = $LASTEXITCODE
Remove-Item -Force $Constraints -ErrorAction SilentlyContinue
if ($code -ne 0) { throw "WanGP requirements install failed" }

Write-Host "Verifying that WanGP imports in its own environment ..." -ForegroundColor Yellow
Push-Location $Wan2GPDir
try {
    & $Py -c "import sys, torch; sys.path.insert(0, '.'); import shared.api; print('WanGP import OK - torch', torch.__version__, '- CUDA available:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "WanGP does not import in $VenvDir - see the error above" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "WanGP environment ready: $Py" -ForegroundColor Green
Write-Host "The backend detects it automatically and runs WanGP from it as a separate process."
Write-Host "Running 'uv sync' in backend/ no longer affects WanGP's packages."
