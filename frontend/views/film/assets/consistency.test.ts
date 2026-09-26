import { describe, expect, it } from 'vitest'
import type { FilmAsset } from '../../../types/film'
import { assetStatus, consistencyOf, inheritedPrompt, looseReferences, sheetImages } from './consistency'

function asset(overrides: Partial<FilmAsset> = {}): FilmAsset {
  return {
    id: 'a1',
    kind: 'character',
    name: 'Mara',
    description: '',
    appearance: '',
    wardrobe: '',
    accessories: '',
    environment: '',
    lighting: '',
    atmosphere: '',
    time_of_day: '',
    prop_details: '',
    style_prompt: '',
    continuity_notes: '',
    reference_images: [],
    lora_id: '',
    lora_trigger: '',
    lora_multiplier: 1,
    seed_lock: null,
    created_at: 0,
    updated_at: 0,
    ...overrides,
  }
}

const guide = { key_traits: ['jacket'], color_palette: ['olive'], mood: 'calm', recommended_prompt: 'olive jacket, calm light' }

describe('consistencyOf', () => {
  it('derives the four booleans from the contract rules', () => {
    expect(consistencyOf(asset())).toEqual({ ref: false, guide: false, lora: false, seed: false, locked: false, count: 0 })
    const full = consistencyOf(asset({ reference_images: ['references/r.png'], style_guide: guide, lora_id: 'lora-1', seed_lock: 777 }))
    expect(full).toEqual({ ref: true, guide: true, lora: true, seed: true, locked: true, count: 4 })
  })

  it('counts partial contracts without locking', () => {
    const c = consistencyOf(asset({ reference_images: ['r'], style_guide: guide }))
    expect(c.count).toBe(2)
    expect(c.locked).toBe(false)
    // seed 0 is a real seed; only null means unlocked.
    expect(consistencyOf(asset({ seed_lock: 0 })).seed).toBe(true)
  })
})

describe('assetStatus', () => {
  it('maps the contract to one badge', () => {
    expect(assetStatus(asset({ kind: 'style' }))).toBe('style')
    expect(assetStatus(asset())).toBe('empty')
    expect(assetStatus(asset({ reference_images: ['r'] }))).toBe('drift')
    expect(assetStatus(asset({ reference_images: ['r'], style_guide: guide }))).toBe('needs-lora')
    expect(assetStatus(asset({ reference_images: ['r'], style_guide: guide, lora_id: 'l' }))).toBe('no-seed')
    expect(assetStatus(asset({ reference_images: ['r'], style_guide: guide, lora_id: 'l', seed_lock: 7 }))).toBe('locked')
  })
})

describe('sheetImages / looseReferences', () => {
  it('picks the newest image per view and leaves the rest as uploads', () => {
    const a = asset({
      reference_images: [
        'references/upload-1.png',
        'references/a1-front-view-2.png',
        'references/a1-three-quarter-view-3.png',
        'references/a1-front-view-9.png', // a re-render: newest wins
      ],
    })
    const sheet = sheetImages(a)
    expect(sheet.map(s => s.view)).toEqual(['front view', 'three-quarter view', 'profile view', 'back view'])
    expect(sheet[0].path).toBe('references/a1-front-view-9.png')
    expect(sheet[1].path).toBe('references/a1-three-quarter-view-3.png')
    expect(sheet[2].path).toBeNull()
    expect(looseReferences(a)).toEqual(['references/upload-1.png', 'references/a1-front-view-2.png'])
  })
})

describe('inheritedPrompt', () => {
  it('matches the backend synthesis order: trigger, name, fields, wardrobe, guide, style assets', () => {
    const mara = asset({
      description: 'ship engineer',
      appearance: 'short dark hair',
      wardrobe: 'green field jacket',
      continuity_notes: 'never inherit me',
      style_guide: guide,
      lora_trigger: 'mara_v1',
    })
    const style = asset({ id: 's1', kind: 'style', name: 'Film look', style_prompt: '35mm grain' })
    const parts = inheritedPrompt(mara, [style])
    expect(parts.map(p => p.source)).toEqual(['trigger', 'name', 'field', 'field', 'wardrobe', 'guide', 'style'])
    expect(parts[0].text).toBe('mara_v1')
    expect(parts.at(-1)?.text).toBe('35mm grain')
    // continuity_notes is not part of the synthesized prompt.
    expect(parts.some(p => p.text.includes('never inherit'))).toBe(false)
  })
})
