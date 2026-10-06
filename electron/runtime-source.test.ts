import { describe, expect, it } from 'vitest'
import { runtimeFallbackUrl, runtimeReleaseBase } from './runtime-source'

// Round 5: the fork's packaged app staged a 3.26 GB Python runtime from
// upstream's release (github.com/Lightricks/ltx-desktop/releases/download/v1.0.1),
// not one built for this fork's backend, with a Lightricks-owned CDN as fallback.
describe('Python runtime source', () => {
  it('downloads from this repo, versioned like the app', () => {
    expect(runtimeReleaseBase('1.0.1')).toBe('https://github.com/jyoung2000/TFG/releases/download/v1.0.1')
  })

  it('never falls back to a Lightricks-owned mirror', () => {
    const fallback = runtimeFallbackUrl('34857b9da6140f492f16db40d5d334170ac5c5f304e47b58633fe814f0074a0f')
    expect(fallback === null || !/lightricks|ltx-desktop-artifacts/i.test(fallback)).toBe(true)
  })

  it('points nowhere near upstream for any version', () => {
    for (const v of ['1.0.1', '1.2.7', '2.0.0-beta.1']) {
      expect(runtimeReleaseBase(v).toLowerCase()).not.toContain('lightricks')
    }
  })
})
