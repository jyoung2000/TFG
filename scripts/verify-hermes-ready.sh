#!/usr/bin/env bash
# Everything docs/HERMES_PROMPT.md relies on must exist in this checkout. Prints ok/MISSING per item; exit 1 on any miss.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
miss=0
for f in scripts/start-backend.ps1 scripts/start-backend.sh scripts/setup-dev.ps1 scripts/setup-dev.sh scripts/ensure-wan2gp.ps1 scripts/ensure-wan2gp.sh \
         backend/tfg_mcp.py backend/agent/mcp_core.py skills/tfg/SKILL.md docs/HERMES_PROMPT.md docs/AGENTS_GUIDE.md docs/AGENT_DEBUG_PROMPT.md \
         docs/RTX_4070_TEST_MATRIX.md docs/CONTAINERS.md docs/TRAINING.md docs/REPRODUCE.md docs/VIDEO_REPRODUCE.md docs/STORYBOARD_3D.md \
         session-notes.md deploy/docker-compose.yml README.md; do
  if [ -e "$root/$f" ]; then echo "ok       $f"; else echo "MISSING  $f"; miss=1; fi
done
for s in backend:dev backend:dev:win agent:mcp setup:dev:win dev e2e test:frontend; do
  if grep -q "\"$s\"" "$root/package.json"; then echo "ok       pnpm $s"; else echo "MISSING  pnpm $s"; miss=1; fi
done
grep -q "Windows WanGP Quick Start" "$root/README.md" && echo "ok       README Windows WanGP Quick Start" || { echo "MISSING  README section"; miss=1; }
exit $miss
