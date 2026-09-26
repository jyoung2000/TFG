#!/usr/bin/env bash
# Create/refresh a LoRA trainer environment beside the backend. Idempotent.
#   scripts/ensure-trainer.sh musubi      → backend/.venv-trainer-musubi + backend/.trainer-musubi (kohya-ss/musubi-tuner, Apache-2.0)
#   scripts/ensure-trainer.sh ai-toolkit  → backend/.venv-trainer-aitoolkit + backend/.trainer-ai-toolkit (ostris/ai-toolkit, MIT)
# Each trainer lives in its own venv so its torch/transformers pins never touch the app's.
# Bootstrap pattern after Open-Generative-AI's engine installer (MIT): clone → venv → pip, all under the app's own folders.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
backend="$root/backend"
which="${1:-musubi}"
case "$which" in
  musubi) repo="https://github.com/kohya-ss/musubi-tuner.git"; venv="$backend/.venv-trainer-musubi"; src="$backend/.trainer-musubi" ;;
  ai-toolkit) repo="https://github.com/ostris/ai-toolkit.git"; venv="$backend/.venv-trainer-aitoolkit"; src="$backend/.trainer-ai-toolkit" ;;
  *) echo "unknown trainer: $which (musubi | ai-toolkit)"; exit 2 ;;
esac
cd "$backend"
if [ -d "$src/.git" ]; then git -C "$src" pull --ff-only 2>&1 | tail -n 2; else git clone --depth 1 "$repo" "$src" 2>&1 | tail -n 2; fi
[ -d "$venv" ] || uv venv "$venv" --python 3.12 2>&1 | tail -n 3
py="$venv/bin/python"
cuda="${TFG_TRAINER_CUDA:-cu128}"
uv pip install --python "$py" --index-url "https://download.pytorch.org/whl/$cuda" torch torchvision 2>&1 | tail -n 3
if [ "$which" = "musubi" ]; then
  uv pip install --python "$py" -e "$src" 2>&1 | tail -n 5
  uv pip install --python "$py" accelerate bitsandbytes 2>&1 | tail -n 3
else
  uv pip install --python "$py" -r "$src/requirements.txt" 2>&1 | tail -n 5
fi
echo
echo "Trainer '$which' ready: $py"
echo "Weights: set them per target in Train → Trainer settings (docs/TRAINING.md)."
