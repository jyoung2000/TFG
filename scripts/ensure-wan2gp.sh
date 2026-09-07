#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
WAN2GP_DIR="${PROJECT_DIR}/Wan2GP"
API_FILE="${WAN2GP_DIR}/shared/api.py"
REPO_URL="${1:-https://github.com/deepbeepmeep/Wan2GP.git}"
EXTERNAL_ROOT="${WANGP_ROOT:-${WANGP_WGP_PATH:-}}"

resolve_external_root() {
  local candidate="$1"
  [ -n "$candidate" ] || return 1
  if [ -f "$candidate" ]; then
    [ "$(basename "$candidate")" = "wgp.py" ] || return 1
    candidate="$(dirname "$candidate")"
  fi
  [ -f "$candidate/wgp.py" ] || return 1
  printf '%s\n' "$candidate"
}

if [ -d "$WAN2GP_DIR" ]; then
  echo "Wan2GP checkout found at $WAN2GP_DIR"
elif RESOLVED_EXTERNAL_ROOT="$(resolve_external_root "$EXTERNAL_ROOT")"; then
  WAN2GP_DIR="$RESOLVED_EXTERNAL_ROOT"
  API_FILE="${WAN2GP_DIR}/shared/api.py"
  echo "Using external Wan2GP checkout at $WAN2GP_DIR"
else
  command -v git >/dev/null 2>&1 || {
    echo "git not found. Install Git before running setup, or set WANGP_ROOT to an existing Wan2GP checkout."
    exit 1
  }
  echo "Cloning Wan2GP into $WAN2GP_DIR..."
  git clone --depth 1 "$REPO_URL" "$WAN2GP_DIR"
fi

if [ ! -f "$API_FILE" ]; then
  echo "Wan2GP checkout does not expose shared/api.py yet. Update the checkout to a version that includes the new API."
  exit 1
fi
