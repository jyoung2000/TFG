#!/usr/bin/env bash
# Create/refresh WanGP's OWN Python environment (Wan2GP/.venv). Idempotent.
# Same contract as ensure-wangp-venv.ps1 — see there for why this exists.
# Env overrides: WANGP_PY_VERSION, WANGP_TORCH, WANGP_TORCHVISION,
# WANGP_TORCHAUDIO, WANGP_TORCH_INDEX; pass --recreate to start fresh.
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
project_dir="$(dirname "$script_dir")"
py_version="${WANGP_PY_VERSION:-3.12}"
torch_v="${WANGP_TORCH:-2.10.0}"
vision_v="${WANGP_TORCHVISION:-0.25.0}"
audio_v="${WANGP_TORCHAUDIO:-2.10.0}"
index="${WANGP_TORCH_INDEX:-https://download.pytorch.org/whl/cu128}"

bash "$script_dir/ensure-wan2gp.sh"

wan="$project_dir/Wan2GP"
if [ ! -f "$wan/wgp.py" ]; then
  if [ -n "${WANGP_ROOT:-}" ] && [ -f "$WANGP_ROOT/wgp.py" ]; then wan="$WANGP_ROOT"; else
    echo "No Wan2GP checkout found (expected $wan or WANGP_ROOT)." >&2; exit 1; fi
fi
venv="$wan/.venv"
py="$venv/bin/python"

if [ "${1:-}" = "--recreate" ] && [ -d "$venv" ]; then rm -rf "$venv"; fi
[ -x "$py" ] || uv venv "$venv" --python "$py_version"

echo "Installing CUDA PyTorch $torch_v from $index ..."
uv pip install --python "$py" "torch==$torch_v" "torchvision==$vision_v" "torchaudio==$audio_v" --index-url "$index"

constraints="$(mktemp)"
trap 'rm -f "$constraints"' EXIT
printf 'torch==%s\ntorchvision==%s\ntorchaudio==%s\n' "$torch_v" "$vision_v" "$audio_v" > "$constraints"
echo "Installing WanGP requirements ..."
uv pip install --python "$py" -r "$wan/requirements.txt" -c "$constraints"

echo "Verifying that WanGP imports in its own environment ..."
(cd "$wan" && "$py" -c "import sys, torch; sys.path.insert(0, '.'); import shared.api; print('WanGP import OK - torch', torch.__version__, '- CUDA available:', torch.cuda.is_available())")

echo
echo "WanGP environment ready: $py"
echo "The backend detects it automatically and runs WanGP from it as a separate process."
