import { describe, expect, it } from 'vitest'
import { describeError } from './error-messages'

describe('describeError', () => {
  it('maps provider key problems to the API Keys action', () => {
    expect(describeError('OPENROUTER_KEY_INVALID: rejected').action).toBe('open-api-keys')
    expect(describeError(new Error('AI_DIRECTOR_KEY_MISSING')).action).toBe('open-api-keys')
    expect(describeError('OPENROUTER_MODEL_NOT_FOUND: x').actionLabel).toBe('Pick model')
  })

  it('maps rate limits and timeouts to retry', () => {
    expect(describeError('OPENROUTER_RATE_LIMITED: slow down').action).toBe('retry')
    expect(describeError('openai_compatible request timed out').action).toBe('retry')
  })

  it('maps runtime problems to the Models tab', () => {
    expect(describeError("No module named 'mmgp'").action).toBe('open-models')
    expect(describeError('CUDA error: out of memory').title).toMatch(/GPU ran out of memory/)
  })

  it('keeps unknown messages verbatim in the detail', () => {
    const result = describeError('something odd happened')
    expect(result.title).toBe('Something went wrong')
    expect(result.detail).toBe('something odd happened')
    expect(result.action).toBeNull()
  })

  it('never throws on non-error inputs', () => {
    expect(describeError(undefined).detail).toBe('Unknown error')
    expect(describeError({ weird: true }).detail).toBe('[object Object]')
  })

  it('does not leak key-shaped text into the friendly title', () => {
    const result = describeError('OPENROUTER_KEY_INVALID sk-or-v1-abcdefghijklmnop')
    expect(result.title).not.toMatch(/sk-or-v1/)
  })
})
