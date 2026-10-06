/**
 * A batch render's result in words (QA pass 2026-10-01): Generate all and a
 * scene's Generate said nothing, so shots skipped for a missing reference or
 * an existing job looked like they had been forgotten.
 */
export function describeBatch(result: { queued: unknown[]; skipped?: { reason: string }[] }): string {
  const skipped = result.skipped ?? []
  const reasons = [...new Set(skipped.map(s => s.reason))].join('; ')
  const queued = `Queued ${result.queued.length} shot${result.queued.length === 1 ? '' : 's'}`
  return skipped.length ? `${queued} · ${skipped.length} skipped: ${reasons}` : queued
}
