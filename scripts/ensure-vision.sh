#!/usr/bin/env bash
# Create/refresh the vision sidecar environment (backend/.venv-vision). Idempotent.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
backend="$root/backend"
venv="$backend/.venv-vision"
cd "$backend"
[ -d "$venv" ] || uv venv "$venv" --python 3.12 2>&1 | tail -n 5
py="$venv/bin/python"
uv pip install --python "$py" -r vision-requirements.txt 2>&1 | tail -n 10
if [ "${TFG_VISION_CUDA:-0}" = "1" ]; then
  uv pip install --python "$py" --index-url https://download.pytorch.org/whl/cu128 torch 2>&1 | tail -n 5
fi
echo
echo "Vision worker ready. Start it with:"
echo "  $py $backend/vision_worker.py --port 8765"
echo "then run the app with TFG_VISION_URL=http://127.0.0.1:8765"
