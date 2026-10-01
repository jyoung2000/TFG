/**
 * One clearly different colour per object in a composer scene, so separate
 * assets read apart at a glance (asked 2026-10-01: figures shared six muted
 * blue-greys and every prop was the same grey).
 */

export const ASSET_COLORS = [
  '#e4572e', // red-orange
  '#29b6f6', // sky blue
  '#76c442', // green
  '#f2c14e', // yellow
  '#b06ad9', // purple
  '#ef6fa6', // pink
  '#2ec4b6', // teal
  '#ff9f43', // orange
  '#5c7cfa', // indigo
  '#a3e635', // lime
] as const

/**
 * The colour an object gets when it enters the scene: its own if it already
 * has a palette colour no one else uses, else the first palette colour not in
 * use (cycling only past ten objects). Old app-assigned greys are replaced.
 */
export function pickAssetColor(current: string | null | undefined, inUse: Iterable<string>): string {
  const used = new Set([...inUse].map(c => c.toLowerCase()))
  const own = (current ?? '').toLowerCase()
  if ((ASSET_COLORS as readonly string[]).includes(own) && !used.has(own)) return own
  const free = ASSET_COLORS.find(c => !used.has(c))
  if (free) return free
  return ASSET_COLORS[used.size % ASSET_COLORS.length]
}
