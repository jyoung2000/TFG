import { describe, expect, it } from 'vitest'
import { faceSummary } from './faceMatch'

/* 2026-10-02: Raven's angle shots were other people's faces and nothing said so. */

describe('faceSummary', () => {
  it('says how close the faces are to the photo', () => {
    expect(faceSummary([0.62, 0.3, null])).toBe(' · face match 0.46 avg, 1/2 same person')
  })
  it('says nothing without scores', () => {
    expect(faceSummary(undefined)).toBe('')
    expect(faceSummary([null])).toBe('')
  })
})
