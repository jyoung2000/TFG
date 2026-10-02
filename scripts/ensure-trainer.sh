#!/usr/bin/env bash
# Create/refresh a LoRA trainer environment. Idempotent.
#   scripts/ensure-trainer.sh musubi      → <trainers>/.venv-trainer-musubi + .trainer-musubi (kohya-ss/musubi-tuner, Apache-2.0)
#   scripts/ensure-trainer.sh ai-toolkit  → <trainers>/.venv-trainer-aitoolkit + .trainer-ai-toolkit (ostris/ai-toolkit, MIT)
#   scripts/ensure-trainer.sh musubi "<folder>"  → into <folder> instead.
# <trainers> is TFG_TRAINER_ROOT when set, else the app data folder's trainers/ (where the app
# looks - backend resolve_trainer_root - and which survives reinstalls).
# Each trainer lives in its own venv so its torch/transformers pins never touch the app's.
# Bootstrap pattern after Open-Generative-AI's engine installer (MIT): clone → venv → pip.
set -euo pipefail
which="${1:-musubi}"
if [ "$(uname)" = "Darwin" ]; then app_data="$HOME/Library/Application Support/LTXDesktop"; else app_data="${XDG_CONFIG_HOME:-$HOME/.config}/LTXDesktop"; fi
backend="${2:-${TFG_TRAINER_ROOT:-$app_data/trainers}}"
mkdir -p "$backend"
case "$which" in
  musubi) repo="https://github.com/kohya-ss/musubi-tuner.git"; venv="$backend/.venv-trainer-musubi"; src="$backend/.trainer-musubi" ;;
  ai-toolkit) repo="https://github.com/ostris/ai-toolkit.git"; venv="$backend/.venv-trainer-aitoolkit"; src="$backend/.trainer-ai-toolkit" ;;
  *) echo "unknown trainer: $which (musubi | ai-toolkit)"; exit 2 ;;
esac
cd "$backend"
if [ -f "$src/.git/HEAD" ]; then git -C "$src" pull --ff-only 2>&1 | tail -n 2; else git clone --depth 1 "$repo" "$src" 2>&1 | tail -n 2; fi
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
