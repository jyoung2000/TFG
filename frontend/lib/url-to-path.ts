/**
 * Extract a filesystem path from a `file://` URL.
 * Returns `null` when the URL is not a file URL.
 */
export function fileUrlToPath(url: string): string | null {
  if (url.startsWith('file://')) {
    let p = decodeURIComponent(url.slice(7)) // file:///Users/x -> /Users/x
    if (/^\/[A-Za-z]:/.test(p)) p = p.slice(1)
    return p
  }
  return null
}
