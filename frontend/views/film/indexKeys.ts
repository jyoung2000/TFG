/**
 * Position-keyed marks across a removal (QA pass 2026-10-01, Build with AI):
 * which plan scenes are unchecked / expanded is kept by position, so removing
 * a scene must forget its mark and move the marks after it up one.
 */

export function dropIndex(indices: Set<number>, removed: number): Set<number> {
  const next = new Set<number>()
  for (const i of indices) if (i !== removed) next.add(i > removed ? i - 1 : i)
  return next
}

export function dropIndexKey<T>(record: Record<number, T>, removed: number): Record<number, T> {
  const next: Record<number, T> = {}
  for (const [key, value] of Object.entries(record)) {
    const i = Number(key)
    if (i !== removed) next[i > removed ? i - 1 : i] = value
  }
  return next
}
