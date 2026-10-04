import { describe, expect, it } from 'vitest'
import { faceMatchNote, imageLoraLabel } from './faceLock'

describe('imageLoraLabel', () => {
  it('says how many LoRAs are on and whether renders are locked to the style sheet', () => {
    expect(imageLoraLabel(0, true)).toBe('LoRA')
    // 2026-10-04: the lock now covers the outfit as well as the face.
    expect(imageLoraLabel(1, true)).toBe('1 LoRA · style-sheet lock')
    expect(imageLoraLabel(2, false)).toBe('2 LoRAs')
  })
})

describe('faceMatchNote', () => {
  it('averages the scores a face lock returned', () => {
    expect(faceMatchNote([0.6, 0.64, null])).toBe('Face match 0.62')
    expect(faceMatchNote(null)).toBe('')
    expect(faceMatchNote([null])).toBe('')
  })
  it('says when the outfit came from the style sheet', () => {
    expect(faceMatchNote([0.6], [true])).toBe('Face match 0.60 · outfit from the style sheet')
    expect(faceMatchNote([0.6], [false])).toBe('Face match 0.60')
    expect(faceMatchNote([null], [true])).toBe('Outfit from the style sheet')
  })
})
