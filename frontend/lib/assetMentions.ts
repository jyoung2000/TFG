/** @Name mentions of style-guide assets in shot text (mirrors the backend matcher). */

const MAX_QUERY = 40
const MAX_SUGGESTIONS = 8

const isAlnum = (ch: string | undefined) => ch !== undefined && /[\p{L}\p{N}]/u.test(ch)

/** The `@` token being typed at the caret, or null when the caret is not in one. */
export function mentionQuery(text: string, caret: number): { start: number; query: string } | null {
  if (caret > text.length) return null
  const start = text.lastIndexOf('@', caret - 1)
  if (start < 0) return null
  if (start > 0 && isAlnum(text[start - 1])) return null
  const query = text.slice(start + 1, caret)
  if (query.length > MAX_QUERY || query.includes('\n')) return null
  return { start, query }
}

/** Assets whose name starts with the query first, then those containing it; at most 8. */
export function filterAssets<T extends { name: string; kind: string }>(assets: T[], query: string): T[] {
  const q = query.trim().toLowerCase()
  const starts: T[] = []
  const contains: T[] = []
  for (const a of assets) {
    const n = a.name.toLowerCase()
    if (n.startsWith(q)) starts.push(a)
    else if (n.includes(q)) contains.push(a)
  }
  return [...starts, ...contains].slice(0, MAX_SUGGESTIONS)
}

/** Replace the `@query` between start and caret with `@Name ` and place the caret after it. */
export function insertMention(text: string, start: number, caret: number, name: string): { text: string; caret: number } {
  const insert = `@${name} `
  return { text: text.slice(0, start) + insert + text.slice(caret), caret: start + insert.length }
}

/** Asset names mentioned in the text: case-insensitive, longest name first, `_` = space. */
export function findMentions(text: string, names: string[]): string[] {
  const norm = (s: string) => s.toLowerCase().replace(/_/g, ' ')
  const hay = norm(text)
  const byLength = [...names].sort((a, b) => b.length - a.length)
  const found = new Set<string>()
  // Spans already claimed by a longer name, so "@Raven QA" does not also match "Raven".
  const claimed: Array<[number, number]> = []
  for (const name of byLength) {
    const needle = norm(name)
    if (!needle.trim()) continue
    let from = 0
    for (;;) {
      const at = hay.indexOf('@' + needle, from)
      if (at < 0) break
      from = at + 1
      const end = at + 1 + needle.length
      if (isAlnum(text[end])) continue
      if (claimed.some(([s, e]) => at >= s && at < e)) continue
      claimed.push([at, end])
      found.add(name)
    }
  }
  return names.filter(n => found.has(n))
}
