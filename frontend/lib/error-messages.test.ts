import { describe, expect, it } from 'vitest'
import { describeError } from './error-messages'

describe('describeError', () => {
  it('sends provider key problems to the tab that holds the fields', () => {
    // Every provider key - text and media alike - is edited in Settings ->
    // AI Models, so these buttons must not open the API Keys tab.
    expect(describeError('OPENROUTER_KEY_INVALID: rejected').action).toBe('open-ai-models')
    expect(describeError(new Error('AI_DIRECTOR_KEY_MISSING')).action).toBe('open-ai-models')
    expect(describeError('OPENROUTER_MODEL_NOT_FOUND: x').actionLabel).toBe('Pick model')
  })

  it('gives the media providers real titles instead of a raw code', () => {
    for (const provider of ['FAL', 'WAVESPEED', 'REPLICATE']) {
      const missing = describeError(`${provider}_KEY_MISSING: no key configured`)
      expect(missing.title).not.toBe('Something went wrong')
      expect(missing.action).toBe('open-ai-models')

      const invalid = describeError(`${provider}_KEY_INVALID: rejected the API key`)
      expect(invalid.title).toMatch(/rejected the API key/)
      expect(invalid.action).toBe('open-ai-models')

      const credits = describeError(`${provider}_CREDITS: insufficient credits`)
      expect(credits.title).toMatch(/credits/i)
      expect(credits.action).toBe('open-ai-models')

      const missingModel = describeError(`${provider}_MODEL_NOT_FOUND: gone`)
      expect(missingModel.title).not.toBe('Something went wrong')
    }
  })

  it('explains a cross-vendor model id', () => {
    const result = describeError("MEDIA_MODEL_PROVIDER_MISMATCH: 'fal-ai/x' is a fal.ai model")
    expect(result.title).toMatch(/different provider/)
    expect(result.action).toBe('open-ai-models')
  })

  it('does not let the generic rate-limit rule swallow a media provider code', () => {
    // FAL_RATE_LIMITED still means "wait", but FAL_CREDITS must not.
    expect(describeError('FAL_CREDITS: insufficient credits').action).not.toBe('retry')
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
