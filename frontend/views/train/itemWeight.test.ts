import { describe, expect, it } from 'vitest'
import { weightBadge } from './itemWeight'

/* 2026-10-02: a LoRA trained on every image equally drifted; the photo and sheet now lead. */

describe('weightBadge', () => {
  it('says how often an image trains and how well its face matches', () => {
    expect(weightBadge({ repeats: 3, face_score: 0.8512 })).toBe('×3 · face 0.85')
    expect(weightBadge({ repeats: 2, face_score: null })).toBe('×2')
    expect(weightBadge({ repeats: 1, face_score: null })).toBe('')
    expect(weightBadge({})).toBe('')
  })
})
