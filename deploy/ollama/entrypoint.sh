#!/bin/sh
# Start Ollama, pull the VLM the vision stack expects once, keep serving.
# KEEP_ALIVE=0 (set by compose) means the model leaves VRAM after each call,
# exactly as the desktop's 12 GB preset configures it.
set -e
ollama serve &
pid=$!
until ollama list >/dev/null 2>&1; do sleep 1; done
model="${TFG_VLM_MODEL:-qwen2.5vl:3b}"
if ! ollama list | awk '{print $1}' | grep -qx "$model"; then
  echo "Pulling $model (first start only)…"
  ollama pull "$model"
fi
wait $pid
