import { describe, expect, it } from 'vitest'
import { commitNumber } from './settingsNumber'

/* QA pass 2026-10-01 (storyboard render defaults). "Preview max seconds" and
 * "Gap between shots" saved on every keystroke and were disabled while
 * saving: typing "12" saved "1" and lost focus; clearing the field snapped it
 * to 4 / 0. They now keep what is typed and commit on Enter / leaving. */

describe('commitNumber', () => {
  it('commits what was typed, within range', () => {
    expect(commitNumber('12', 4, { min: 1, max: 20 })).toBe(12)
    expect(commitNumber('2.5', 0, { min: 0, max: 10 })).toBe(2.5)
  })

  it('clamps to the range', () => {
    expect(commitNumber('99', 4, { min: 1, max: 20 })).toBe(20)
    expect(commitNumber('0', 4, { min: 1, max: 20 })).toBe(1)
  })

  it('an empty or unreadable field keeps the saved value (no change)', () => {
    expect(commitNumber('', 4, { min: 1, max: 20 })).toBeNull()
    expect(commitNumber('abc', 4, { min: 1, max: 20 })).toBeNull()
  })

  it('the same value is no change', () => {
    expect(commitNumber('4', 4, { min: 1, max: 20 })).toBeNull()
  })
})
