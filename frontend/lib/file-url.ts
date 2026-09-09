/**
 * Turn a path on this machine into a URL a media element can load.
 *
 * Under Electron that is a `file://` URL, which the renderer is allowed to
 * read. In a plain browser (`pnpm dev:ui`) `file://` is blocked, so the dev
 * server serves the file instead — see `devtools/ui-mock`. The branch below is
 * compiled out of production builds, where the env flag is undefined.
 */

const UI_MOCK_FILE_ROUTE = import.meta.env.VITE_UI_MOCK === '1' ? '/api/__ui_mock/file' : ''

export function toFileUrl(path: string): string {
  const normalized = path.replace(/\\/g, '/')
  if (UI_MOCK_FILE_ROUTE) {
    return `${UI_MOCK_FILE_ROUTE}?path=${encodeURIComponent(normalized)}`
  }
  return normalized.startsWith('/') ? `file://${normalized}` : `file:///${normalized}`
}
