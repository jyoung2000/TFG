/**
 * The consistency contract: four independent facts about a FilmAsset that
 * together say whether LTX/Wan can reproduce it shot after shot.
 *
 *   REF   — at least one reference image
 *   GUIDE — a style guide extracted (or written) for it
 *   LORA  — a registry LoRA bound to it
 *   SEED  — a locked seed
 *
 * All four ⇒ production-locked. Everything in the Assets tab derives from
 * these rules; keep them here, pure and unit-tested.
 */

import type { FilmAsset } from '../../../types/film'

export interface Consistency {
  ref: boolean
  guide: boolean
  lora: boolean
  seed: boolean
  /** All four are true. */
  locked: boolean
  /** How many of the four are true (0–4). */
  count: number
}

export function consistencyOf(asset: FilmAsset): Consistency {
  const ref = asset.reference_images.length > 0
  const guide = !!asset.style_guide
  const lora = asset.lora_id !== ''
  const seed = asset.seed_lock !== null
  const count = [ref, guide, lora, seed].filter(Boolean).length
  return { ref, guide, lora, seed, locked: count === 4, count }
}

/**
 * The one badge an asset card wears. Style assets are exempt from the
 * contract (they apply to every shot); an untouched asset shows nothing.
 */
export type AssetStatus = 'locked' | 'needs-lora' | 'no-seed' | 'drift' | 'style' | 'empty'

export function assetStatus(asset: FilmAsset): AssetStatus {
  if (asset.kind === 'style') return 'style'
  const c = consistencyOf(asset)
  if (c.locked) return 'locked'
  if (c.count === 0) return 'empty'
  if (c.ref && !c.guide && !c.lora && !c.seed) return 'drift'
  if (c.guide && !c.lora) return 'needs-lora'
  return 'no-seed'
}

/** The four views a reference sheet renders, in backend order. */
export const SHEET_VIEWS = ['front view', 'three-quarter view', 'profile view', 'back view'] as const
export type SheetView = (typeof SHEET_VIEWS)[number]

/**
 * Reference-sheet images are ordinary reference images, but both the real
 * backend and the ui-mock name the file after its view ("…-front-view…"),
 * so the newest match per view can be shown in the labelled 4-up hero.
 */
export function sheetImages(asset: FilmAsset): { view: SheetView; path: string | null }[] {
  return SHEET_VIEWS.map(view => {
    const token = view.replace(/ /g, '-')
    const matches = asset.reference_images.filter(p => p.includes(token))
    return { view, path: matches.length ? matches[matches.length - 1] : null }
  })
}

/** Reference images that are not shown as a sheet tile (uploads and extras). */
export function looseReferences(asset: FilmAsset): string[] {
  const used = new Set(sheetImages(asset).map(s => s.path).filter(Boolean))
  return asset.reference_images.filter(p => !used.has(p))
}

/**
 * What a shot featuring this asset inherits, mirroring the backend's
 * `film_prompt.py` synthesis (trigger leads, then name, then the detail
 * fields in parentheses, then the style guide's prompt; style assets'
 * `style_prompt` is appended to every shot). This is a preview of the real
 * pipeline, not a second pipeline — keep the order in sync with
 * `backend/film/film_prompt.py`.
 */
export interface InheritedPart {
  text: string
  source: 'trigger' | 'name' | 'field' | 'wardrobe' | 'guide' | 'style'
}

export function inheritedPrompt(asset: FilmAsset, styleAssets: FilmAsset[]): InheritedPart[] {
  const parts: InheritedPart[] = []
  if (asset.lora_trigger.trim()) parts.push({ text: asset.lora_trigger.trim(), source: 'trigger' })
  parts.push({ text: asset.name, source: 'name' })
  const fields =
    asset.kind === 'character'
      ? [asset.description, asset.appearance]
      : asset.kind === 'location'
        ? [asset.description, asset.environment, asset.atmosphere]
        : [asset.prop_details, asset.description]
  for (const value of fields) if (value.trim()) parts.push({ text: value.trim(), source: 'field' })
  if (asset.kind === 'character' && asset.wardrobe.trim()) parts.push({ text: asset.wardrobe.trim(), source: 'wardrobe' })
  if (asset.style_guide?.recommended_prompt.trim()) parts.push({ text: asset.style_guide.recommended_prompt.trim(), source: 'guide' })
  for (const style of styleAssets) {
    if (style.kind === 'style' && style.style_prompt.trim() && style.id !== asset.id)
      parts.push({ text: style.style_prompt.trim(), source: 'style' })
  }
  return parts
}
