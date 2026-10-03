import { describe, expect, it } from 'vitest'
import { faceMatchNote, imageLoraLabel } from './faceLock'

describe('imageLoraLabel', () => {
  it('says how many LoRAs are on and whether the face is locked', () => {
    expect(imageLoraLabel(0, true)).toBe('LoRA')
    expect(imageLoraLabel(1, true)).toBe('1 LoRA · face lock')
    expect(imageLoraLabel(2, false)).toBe('2 LoRAs')
  })
})

describe('faceMatchNote', () => {
  it('averages the scores a face lock returned', () => {
    expect(faceMatchNote([0.6, 0.64, null])).toBe('Face match 0.62')
    expect(faceMatchNote(null)).toBe('')
    expect(faceMatchNote([null])).toBe('')
  })
})
