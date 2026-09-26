/**
 * Client-side merge rules for ShotSpec edits — the renderer never invents
 * analysis, it only combines what the backend returned with what the user
 * typed. Mirrors the precedence in `backend/film/shot_spec_fusion.py`
 * (design after macchant/imex-next `fusion.ts`, MIT).
 */

import { SPEC_SECTIONS, type ShotSpec, type SpecSection } from '../../types/shotspec'

export const PROVENANCE_RANK: Record<string, number> = { user: -1, measured: 0, depth: 0, flow: 0, florence: 1, clip: 2, vlm: 3, '': 9 }

/**
 * Bring a fresh analysis into a spec the user has been editing: locked
 * sections stay, unlocked sections take the incoming value when its source
 * ranks at least as high as the current one.
 */
export function mergeSpecs(base: ShotSpec, update: ShotSpec): ShotSpec {
  const merged: ShotSpec = { ...base, confidence: { ...base.confidence }, provenance: { ...base.provenance }, locks: { ...base.locks } }
  for (const section of SPEC_SECTIONS) {
    if (base.locks[section]) continue
    const incoming = update.provenance[section] ?? ''
    if (!incoming) continue
    const current = base.provenance[section] ?? ''
    if (!current || (PROVENANCE_RANK[incoming] ?? 9) <= (PROVENANCE_RANK[current] ?? 9)) {
      ;(merged as unknown as Record<SpecSection, unknown>)[section] = structuredClone(update[section])
      merged.provenance[section] = incoming
      merged.confidence[section] = update.confidence[section] ?? 0
    }
  }
  if (update.source.hash) merged.source = { ...update.source }
  return merged
}

/** Which sections a new analysis would change, for a "3 sections will update" notice. */
export function sectionsThatWouldChange(base: ShotSpec, update: ShotSpec): SpecSection[] {
  const after = mergeSpecs(base, update)
  return SPEC_SECTIONS.filter(section => JSON.stringify(after[section]) !== JSON.stringify(base[section]))
}
