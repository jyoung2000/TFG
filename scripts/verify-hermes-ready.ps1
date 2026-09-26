# Everything docs\HERMES_PROMPT.md relies on must exist in this checkout. Prints ok/MISSING per item; exit 1 on any miss.
$root = Split-Path -Parent $PSScriptRoot
$miss = 0
$files = @('scripts\start-backend.ps1','scripts\start-backend.sh','scripts\setup-dev.ps1','scripts\setup-dev.sh','scripts\ensure-wan2gp.ps1','scripts\ensure-wan2gp.sh','scripts\ensure-wangp-venv.ps1','scripts\ensure-wangp-venv.sh','backend\wangp_worker.py',
  'backend\tfg_mcp.py','backend\agent\mcp_core.py','skills\tfg\SKILL.md','docs\HERMES_PROMPT.md','docs\AGENTS_GUIDE.md','docs\AGENT_DEBUG_PROMPT.md',
  'docs\RTX_4070_TEST_MATRIX.md','docs\CONTAINERS.md','docs\TRAINING.md','docs\REPRODUCE.md','docs\VIDEO_REPRODUCE.md','docs\STORYBOARD_3D.md',
  'session-notes.md','deploy\docker-compose.yml','README.md')
foreach ($f in $files) { if (Test-Path (Join-Path $root $f)) { Write-Host "ok       $f" } else { Write-Host "MISSING  $f"; $miss = 1 } }
$pkg = Get-Content (Join-Path $root 'package.json') -Raw
foreach ($s in @('backend:dev','backend:dev:win','agent:mcp','setup:dev:win','dev','e2e','test:frontend')) {
  if ($pkg -match [regex]::Escape("`"$s`"")) { Write-Host "ok       pnpm $s" } else { Write-Host "MISSING  pnpm $s"; $miss = 1 }
}
if ((Get-Content (Join-Path $root 'README.md') -Raw) -match 'Windows WanGP Quick Start') { Write-Host 'ok       README Windows WanGP Quick Start' } else { Write-Host 'MISSING  README section'; $miss = 1 }
exit $miss
