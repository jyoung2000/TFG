/**
 * Turn a path on this machine into a URL a media element can load.
 *
 * Under Electron that is a `file://` URL, which the renderer is allowed to
 * read. A browser is not: with `pnpm dev:ui` the dev server serves the file
 * instead, and in the standalone build a resolver hands back a `data:` or
 * `blob:` URL. Both branches are compiled out of the app build, where the env
 * flags are undefined.
 */

import { mediaResolver } from './media-resolver'

const UI_MOCK_FILE_ROUTE = import.meta.env.VITE_UI_MOCK === '1' ? '/api/__ui_mock/file' : ''

export function toFileUrl(path: string): string {
  const normalized = path.replace(/\\/g, '/')
  const standalone = mediaResolver()
  if (standalone) return standalone.file(normalized)
  if (UI_MOCK_FILE_ROUTE) {
    return `${UI_MOCK_FILE_ROUTE}?path=${encodeURIComponent(normalized)}`
  }
  return normalized.startsWith('/') ? `file://${normalized}` : `file:///${normalized}`
}
