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
if (Test-Path (Join-Path $src ".git")) { git -C $src pull --ff-only 2>&1 | Select-Object -Last 2 } else { git clone --depth 1 $repo $src 2>&1 | Select-Object -Last 2 }
if (-not (Test-Path $venv)) { uv venv $venv --python 3.12 2>&1 | Select-Object -Last 3 }
$py = Join-Path $venv "Scripts\python.exe"
$cuda = if ($env:TFG_TRAINER_CUDA) { $env:TFG_TRAINER_CUDA } else { "cu128" }
uv pip install --python $py --index-url "https://download.pytorch.org/whl/$cuda" torch torchvision 2>&1 | Select-Object -Last 3
if ($Which -eq "musubi") {
  uv pip install --python $py -e $src 2>&1 | Select-Object -Last 5
  uv pip install --python $py accelerate bitsandbytes 2>&1 | Select-Object -Last 3
} else {
  uv pip install --python $py -r (Join-Path $src "requirements.txt") 2>&1 | Select-Object -Last 5
}
Write-Host ""
Write-Host "Trainer '$Which' ready: $py"
Write-Host "Weights: set them per target in Train -> Trainer settings (docs/TRAINING.md)."
