/**
 * Style-sheet lock (user, 2026-10-03: "How can we use the styleguide to create a
 * consistent face for the LoRA"; 2026-10-04: "The LoRA and outfit should be
 * accurate to the face sheet and styleguide"): a render made with a character
 * LoRA trained here gets its outfit, then its face, re-composed from the style
 * sheet (backend film/face_lock.py). On by default; this is what the toolbar shows.
 */

/** The image toolbar's LoRA button: what is on at a glance. */
export function imageLoraLabel(count: number, faceLock: boolean): string {
  if (count <= 0) return 'LoRA'
  return `${count} LoRA${count === 1 ? '' : 's'}${faceLock ? ' · style-sheet lock' : ''}`
}

/**
 * "Face match 0.62 · outfit from the style sheet" for a finished render; ''
 * when no lock ran.
 */
export function faceMatchNote(scores: (number | null)[] | null | undefined, outfitLocked?: boolean[] | null): string {
  const known = (scores ?? []).filter((s): s is number => typeof s === 'number')
  const outfit = (outfitLocked ?? []).some(Boolean)
  const face = known.length ? `Face match ${(known.reduce((a, b) => a + b, 0) / known.length).toFixed(2)}` : ''
  if (!face) return outfit ? 'Outfit from the style sheet' : ''
  return outfit ? `${face} · outfit from the style sheet` : face
}
