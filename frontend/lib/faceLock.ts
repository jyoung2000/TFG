/**
 * Face lock (user, 2026-10-03: "How can we use the styleguide to create a
 * consistent face for the LoRA"): a render made with a character LoRA trained
 * here gets its face re-composed from the style sheet's front face
 * (backend film/face_lock.py). On by default; this is what the toolbar shows.
 */

/** The image toolbar's LoRA button: what is on at a glance. */
export function imageLoraLabel(count: number, faceLock: boolean): string {
  if (count <= 0) return 'LoRA'
  return `${count} LoRA${count === 1 ? '' : 's'}${faceLock ? ' · face lock' : ''}`
}

/** "Face match 0.62" for a finished render's scores; '' when no face lock ran. */
export function faceMatchNote(scores: (number | null)[] | null | undefined): string {
  const known = (scores ?? []).filter((s): s is number => typeof s === 'number')
  if (known.length === 0) return ''
  return `Face match ${(known.reduce((a, b) => a + b, 0) / known.length).toFixed(2)}`
}
