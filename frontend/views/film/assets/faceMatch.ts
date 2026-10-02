/**
 * Face match of rendered views to the identity photo, in words (2026-10-02):
 * the backend keeps the best of several candidates by OpenCV SFace cosine,
 * where 0.363 or more is the same person. Views with no face (a back view) and
 * a backend without the matcher report null.
 */
export const SAME_PERSON = 0.363

export function faceSummary(scores: (number | null)[] | undefined): string {
  const seen = (scores ?? []).filter((s): s is number => typeof s === 'number')
  if (seen.length === 0) return ''
  const same = seen.filter(s => s >= SAME_PERSON).length
  const average = seen.reduce((a, b) => a + b, 0) / seen.length
  return ` · face match ${average.toFixed(2)} avg, ${same}/${seen.length} same person`
}
