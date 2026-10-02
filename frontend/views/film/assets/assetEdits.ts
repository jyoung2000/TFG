/**
 * The asset form's pending edits (QA pass 2026-10-01). The form used to copy
 * the whole asset into a draft when it opened, so fields the AI filled later
 * (the style guide writes appearance / wardrobe / description) were shown
 * stale and saved back over the AI's text. The form now keeps only what the
 * user typed; this is what a save sends.
 */

import type { FilmAsset } from '../../../types/film'

export const ASSET_TEXT_FIELDS = [
  'name', 'description', 'appearance', 'wardrobe', 'accessories', 'environment', 'lighting',
  'atmosphere', 'time_of_day', 'prop_details', 'style_prompt', 'continuity_notes',
] as const

export type AssetTextField = (typeof ASSET_TEXT_FIELDS)[number]
export type AssetEdits = Partial<Record<AssetTextField, string>>

/** The edited fields that differ from the live asset; a blank name is never sent. */
export function assetUpdates(edits: AssetEdits, asset: FilmAsset): Partial<Record<AssetTextField, string>> {
  const updates: Partial<Record<AssetTextField, string>> = {}
  for (const key of ASSET_TEXT_FIELDS) {
    let value = edits[key]
    if (value === undefined) continue
    if (key === 'name') {
      value = value.trim()
      if (!value) continue
    }
    if (value !== ((asset as unknown as Record<string, unknown>)[key] ?? '')) updates[key] = value
  }
  return updates
}
