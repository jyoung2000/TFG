/**
 * Where the renderer gets a URL for a piece of media.
 *
 * Normally there is nothing to decide: captures and renders come from the
 * backend over HTTP, and local files get a `file://` URL Electron can read.
 * The standalone UI build has no server and no filesystem access, so it
 * registers a resolver that hands back `data:` and `blob:` URLs instead.
 *
 * The flag is a build-time literal, so all of this is eliminated from the app
 * build — where no resolver is ever registered anyway.
 */

export interface MediaResolver {
  media(projectId: string, path: string): Promise<string>
  output(path: string): Promise<string>
  file(path: string): string
}

export const STANDALONE_UI = import.meta.env.VITE_UI_STANDALONE === '1'

let resolver: MediaResolver | null = null

export function setMediaResolver(next: MediaResolver): void {
  resolver = next
}

export function mediaResolver(): MediaResolver | null {
  return STANDALONE_UI ? resolver : null
}
