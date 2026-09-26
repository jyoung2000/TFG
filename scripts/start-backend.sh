#!/usr/bin/env bash
# Start the TFG backend headless (no Electron) — for agents (Hermes, MCP clients), servers and tests.
#   scripts/start-backend.sh                # http://127.0.0.1:8000, no token (loopback), data in ~/.local/share/tfg
#   LTX_AUTH_TOKEN=secret scripts/start-backend.sh   # require a bearer token (also for /mcp)
#   LTX_PORT=8010 WANGP_ROOT=/opt/Wan2GP scripts/start-backend.sh
# WanGP is found at ./Wan2GP (from scripts/ensure-wan2gp.sh or pnpm setup:dev:*) or via WANGP_ROOT.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
py="${LTX_BACKEND_PYTHON:-$root/backend/.venv/bin/python}"
[ -x "$py" ] || { echo "backend venv missing ($py). Run: pnpm setup:dev:linux (or :mac)"; exit 2; }
export LTX_APP_DATA_DIR="${LTX_APP_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/tfg}"
export LTX_PORT="${LTX_PORT:-8000}"
if [ -z "${LTX_AUTH_TOKEN:-}" ]; then export LTX_OPEN_API=1; fi
if [ -z "${WANGP_ROOT:-}" ] && [ -f "$root/Wan2GP/wgp.py" ]; then export WANGP_ROOT="$root/Wan2GP"; fi
mkdir -p "$LTX_APP_DATA_DIR"
echo "TFG backend → http://127.0.0.1:$LTX_PORT  (data: $LTX_APP_DATA_DIR; WanGP: ${WANGP_ROOT:-not found → API/LTX pipeline mode}; auth: ${LTX_AUTH_TOKEN:+token}${LTX_AUTH_TOKEN:-open on loopback})"
echo "MCP: TFG_BACKEND_URL=http://127.0.0.1:$LTX_PORT ${LTX_AUTH_TOKEN:+TFG_AUTH_TOKEN=<token> }$py $root/backend/tfg_mcp.py   |   POST http://127.0.0.1:$LTX_PORT/mcp"
cd "$root/backend"
exec "$py" ltx2_server.py
