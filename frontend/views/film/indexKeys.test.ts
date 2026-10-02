import { describe, expect, it } from 'vitest'
import { dropIndex, dropIndexKey } from './indexKeys'

/* QA pass 2026-10-01 (Build with AI). Which plan scenes are unchecked (and
 * expanded) was kept by position; removing a scene shifted the scenes after
 * it but not those marks, so the wrong scenes were left out of "Apply". */

describe('dropIndex', () => {
  it('forgets the removed position and moves later ones up', () => {
    expect([...dropIndex(new Set([0, 2, 3]), 1)].sort()).toEqual([0, 1, 2])
    expect([...dropIndex(new Set([1, 3]), 1)]).toEqual([2])
  })
})

describe('dropIndexKey', () => {
  it('does the same for a position-keyed record', () => {
    expect(dropIndexKey({ 0: true, 2: true, 3: false }, 1)).toEqual({ 0: true, 1: true, 2: false })
  })
})
