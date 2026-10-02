# Create/refresh a LoRA trainer environment beside the backend (Windows). Idempotent.
#   scripts/ensure-trainer.ps1 musubi      -> backend/.venv-trainer-musubi + backend/.trainer-musubi (kohya-ss/musubi-tuner, Apache-2.0)
#   scripts/ensure-trainer.ps1 ai-toolkit  -> backend/.venv-trainer-aitoolkit + backend/.trainer-ai-toolkit (ostris/ai-toolkit, MIT)
# Each trainer lives in its own venv so its torch/transformers pins never touch the app's.
param([string]$Which = "musubi")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backend = Join-Path $root "backend"
switch ($Which) {
  "musubi" { $repo = "https://github.com/kohya-ss/musubi-tuner.git"; $venv = Join-Path $backend ".venv-trainer-musubi"; $src = Join-Path $backend ".trainer-musubi" }
  "ai-toolkit" { $repo = "https://github.com/ostris/ai-toolkit.git"; $venv = Join-Path $backend ".venv-trainer-aitoolkit"; $src = Join-Path $backend ".trainer-ai-toolkit" }
  default { Write-Error "unknown trainer: $Which (musubi | ai-toolkit)"; exit 2 }
}
Set-Location $backend
# Native tools write progress to stderr; under "Stop", Windows PowerShell 5 took
# git's "Cloning into..." for a failure and aborted mid-clone (2026-10-02).
# Each step is judged by its exit code instead.
function Step([string]$What, [scriptblock]$Block, [int]$Tail = 3) {
  $ErrorActionPreference = "Continue"
  & $Block 2>&1 | ForEach-Object { "$_" } | Select-Object -Last $Tail
  if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}
# A real clone has .git/HEAD; a bare or empty .git (a clone cut short) would
# send "git -C" up to the enclosing repository instead.
if (Test-Path (Join-Path $src ".git\HEAD")) { Step "git pull" { git -C $src pull --ff-only } } else {
  if (Test-Path $src) { Remove-Item -Recurse -Force $src }  # a clone cut short
  Step "git clone" { git clone --depth 1 $repo $src }
}
if (-not (Test-Path $venv)) { Step "uv venv" { uv venv $venv --python 3.12 } }
$py = Join-Path $venv "Scripts\python.exe"
$cuda = if ($env:TFG_TRAINER_CUDA) { $env:TFG_TRAINER_CUDA } else { "cu128" }
Step "torch install" { uv pip install --python $py --index-url "https://download.pytorch.org/whl/$cuda" torch torchvision }
if ($Which -eq "musubi") {
  Step "musubi install" { uv pip install --python $py -e $src } 5
  Step "accelerate install" { uv pip install --python $py accelerate bitsandbytes }
} else {
  Step "requirements install" { uv pip install --python $py -r (Join-Path $src "requirements.txt") } 5
}
Write-Host ""
Write-Host "Trainer '$Which' ready: $py"
Write-Host "Weights: set them per target in Train -> Trainer settings (docs/TRAINING.md)."
