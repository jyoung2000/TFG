// Where the packaged app downloads its Python runtime (python-embed-win32).
// No Electron imports, so the unit tests can load it.

// This fork's releases, never upstream's: upstream's runtime is built for
// upstream's backend, not this one (F-066 in docs/DEBUG_REPORT_hermes.md).
export const RUNTIME_RELEASES_REPO = 'jyoung2000/TFG'

/**
 * Hash-keyed single-file mirror tried when the release download fails. The
 * only one that existed is Lightricks-owned, so this fork has none.
 */
export const RUNTIME_FALLBACK_CDN_BASE: string | null = null

export function runtimeReleaseBase(version: string): string {
  return `https://github.com/${RUNTIME_RELEASES_REPO}/releases/download/v${version}`
}

export function runtimeFallbackUrl(depsHash: string | null): string | null {
  if (!depsHash || !RUNTIME_FALLBACK_CDN_BASE) return null
  return `${RUNTIME_FALLBACK_CDN_BASE}/python-embed-win32/${depsHash}/python-embed-win32.tar.gz`
}
