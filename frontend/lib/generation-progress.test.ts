import { describe, expect, it } from 'vitest'
import { expectedInferenceSeconds, inferenceStatusMessage, interpolateInferenceProgress } from './generation-progress'

describe('interpolateInferenceProgress', () => {
  it('is still moving long after the old 45 s fallback had frozen at 95%', () => {
    const expected = expectedInferenceSeconds('fast')
    const at45 = interpolateInferenceProgress(45, expected, 0)
    const at175 = interpolateInferenceProgress(175, expected, 0)
    const at400 = interpolateInferenceProgress(400, expected, 0)
    expect(at45).toBeLessThan(50)
    expect(at175).toBeGreaterThan(at45)
    expect(at400).toBeGreaterThan(at175)
  })

  it('never claims completion and never goes backwards past what the backend reported', () => {
    expect(interpolateInferenceProgress(10_000, 150, 0)).toBe(94)
    expect(interpolateInferenceProgress(0, 150, 60)).toBe(60)
    expect(interpolateInferenceProgress(0, 150, 99)).toBe(94)
  })

  it('starts at 15%', () => {
    expect(interpolateInferenceProgress(0, 150, 0)).toBe(15)
  })
})

describe('expectedInferenceSeconds', () => {
  it('reflects the measured 4070 renders, not a 45 s guess', () => {
    expect(expectedInferenceSeconds('fast')).toBeGreaterThanOrEqual(120)
    expect(expectedInferenceSeconds('pro')).toBeGreaterThan(expectedInferenceSeconds('fast'))
  })
})

describe('inferenceStatusMessage', () => {
  it('explains a render that outlives its estimate', () => {
    expect(inferenceStatusMessage(10, 150, 'Generating...')).toBe('Generating...')
    expect(inferenceStatusMessage(200, 150, 'Generating...')).toMatch(/taking longer than usual, still working/)
  })
})
