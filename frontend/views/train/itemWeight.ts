/**
 * What a training image's card says about its weight (2026-10-02): how many
 * times an epoch sees it and how closely its face matches the dataset's photo.
 */
export function weightBadge(item: { repeats?: number; face_score?: number | null }): string {
  const parts: string[] = []
  if ((item.repeats ?? 1) > 1) parts.push(`×${item.repeats}`)
  if (typeof item.face_score === 'number') parts.push(`face ${item.face_score.toFixed(2)}`)
  return parts.join(' · ')
}

/** The labels of a LoRA preview's views, in render order (backend PREVIEW_VIEWS). */
export const PREVIEW_LABELS = ['Close-up', 'Medium ¾', 'Full body', 'Full profile']
