#!/usr/bin/env node
/**
 * build-win-retry.mjs — electron-builder wrapper for Windows.
 *
 * electron-builder extracts the Electron zip into release/win-unpacked.tmp
 * and then renames it to release/win-unpacked. On this machine the rename
 * reliably fails with EPERM (an AV/filter handle persists on freshly
 * extracted dirs; delete still works, rename-reparent does not).
 *
 * This wrapper runs electron-builder with --dir; if it fails with the known
 * EPERM-rename signature, it finishes the step manually (copy .tmp ->
 * win-unpacked, delete .tmp) and re-runs electron-builder WITHOUT --dir so
 * it proceeds straight to NSIS using the now-present win-unpacked.
 */
import { execSync, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const root = process.cwd()
const release = path.join(root, 'release')
const tmp = path.join(release, 'win-unpacked.tmp')
const final = path.join(release, 'win-unpacked')

// electron-builder ALWAYS extracts the Electron zip and renames it into
// appOutDir, even when appOutDir already exists — it deletes the target
// first. Its rename hits EPERM on this machine (AV handle on freshly
// extracted dirs). The robust bypass: point electronDist at a pre-extracted
// copy of the cached Electron zip, which skips download+extract+rename.
const electronCache = path.join(process.env.LOCALAPPDATA ?? '', 'electron', 'Cache')

function findCachedElectronZip() {
  if (!fs.existsSync(electronCache)) return null
  const version = JSON.parse(fs.readFileSync(path.join(root, 'node_modules', 'electron', 'package.json'), 'utf8')).version
  for (const hashDir of fs.readdirSync(electronCache)) {
    const candidate = path.join(electronCache, hashDir, `electron-v${version}-win32-x64.zip`)
    if (fs.existsSync(candidate)) return candidate
  }
  return null
}

function run(args) {
  const r = spawnSync('pnpm', ['exec', 'electron-builder', ...args], {
    stdio: 'inherit',
    shell: true,
    cwd: root,
  })
  return r.status ?? 1
}

function repairFromTmp() {
  if (!fs.existsSync(tmp)) return false
  console.log('[build-win-retry] repairing: copy win-unpacked.tmp -> win-unpacked')
  fs.rmSync(final, { recursive: true, force: true })
  fs.cpSync(tmp, final, { recursive: true })
  fs.rmSync(tmp, { recursive: true, force: true })
  return fs.existsSync(path.join(final, 'electron.exe'))
}

// Pre-extract the cached Electron zip to release/electron-dist so
// electron-builder's download+extract+rename step is skipped entirely.
// electronDist must contain the unpacked Electron directly.
function prepareElectronDist() {
  const zip = findCachedElectronZip()
  if (!zip) return null
  const dist = path.join(release, 'electron-dist')
  if (fs.existsSync(path.join(dist, 'electron.exe'))) return dist
  console.log('[build-win-retry] pre-extracting', path.basename(zip), '-> release/electron-dist')
  fs.rmSync(dist, { recursive: true, force: true })
  fs.mkdirSync(dist, { recursive: true })
  // Windows tar cannot write into a backslash path with -C in some builds;
  // a plain unzip via PowerShell Expand-Archive is dependable here.
  execSync(
    `powershell -NoProfile -Command "Expand-Archive -LiteralPath '${zip}' -DestinationPath '${dist}' -Force"`,
    { stdio: 'ignore' },
  )
  return fs.existsSync(path.join(dist, 'electron.exe')) ? dist : null
}

const dist = prepareElectronDist()
const baseArgs = process.argv.slice(2).length ? process.argv.slice(2) : ['--win', '--publish', 'never']
const args = dist ? [...baseArgs, '--config.electronDist=' + dist] : baseArgs
const exitCode = run(args)
if (exitCode === 0) {
  process.exit(0)
}

// Heuristic: check the last output for the EPERM rename signature by
// re-running is expensive, so simply attempt the repair and retry once.
if (repairFromTmp()) {
  console.log('[build-win-retry] repaired; retrying electron-builder (no --dir)')
  const retryArgs = process.argv.slice(2).filter(a => a !== '--dir')
  const rc = run(retryArgs.length ? retryArgs : ['--win', '--publish', 'never'])
  process.exit(rc)
}

console.error('[build-win-retry] build failed and no .tmp directory to repair from')
process.exit(exitCode)
