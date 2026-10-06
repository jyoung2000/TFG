/**
 * Number settings that commit when the user is done typing (QA pass
 * 2026-10-01): the render-default inputs saved on every keystroke and locked
 * while saving, so "12" became "1" and a cleared field snapped to a default.
 * Returns the value to save, or null for no change (empty / unreadable /
 * unchanged).
 */
export function commitNumber(text: string, current: number, range: { min: number; max: number }): number | null {
  if (!text.trim()) return null
  const value = Number(text)
  if (!Number.isFinite(value)) return null
  const clamped = Math.min(range.max, Math.max(range.min, value))
  return clamped === current ? null : clamped
}
