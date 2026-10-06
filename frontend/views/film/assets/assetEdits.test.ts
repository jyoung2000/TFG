import { describe, expect, it } from 'vitest'
import { assetUpdates } from './assetEdits'
import type { FilmAsset } from '../../../types/film'

/* QA pass 2026-10-01. The asset form copied the whole asset into a draft when
 * it opened. "Generate style guide" then filled appearance / wardrobe /
 * description on the server, but the form kept the old text - and the next
 * Save (or leaving the name field) wrote that stale text back over the AI's.
 * The form now holds only the user's edits; everything else is the live asset. */

const asset = (over: Partial<FilmAsset> = {}): FilmAsset => ({ id: 'a1', name: 'Woman', description: '', appearance: '', wardrobe: '', ...over } as FilmAsset)

describe('assetUpdates', () => {
  it('sends nothing when the user changed nothing, even after the AI filled fields', () => {
    expect(assetUpdates({}, asset({ appearance: 'long dark hair', wardrobe: 'black leather' }))).toEqual({})
  })

  it('sends only the fields the user edited', () => {
    const live = asset({ appearance: 'long dark hair (AI)', wardrobe: 'black leather (AI)' })
    expect(assetUpdates({ wardrobe: 'red dress' }, live)).toEqual({ wardrobe: 'red dress' })
  })

  it('skips an edit that ends up as what the asset already says', () => {
    expect(assetUpdates({ appearance: 'same' }, asset({ appearance: 'same' }))).toEqual({})
  })

  it('never saves a blank name; trims the name', () => {
    expect(assetUpdates({ name: '   ' }, asset())).toEqual({})
    expect(assetUpdates({ name: '  Heroine ' }, asset())).toEqual({ name: 'Heroine' })
  })
})
