import { describe, expect, it } from 'vitest'
import { filterOptions, nextActiveIndex, type SearchableOption } from './searchable-select'

const opts: SearchableOption[] = [
  { value: 'ltx-2', label: 'LTX Video 2', detail: 'fast distilled', group: 'Video' },
  { value: 'wan-2.2', label: 'Wan 2.2', detail: 'high quality', group: 'Video' },
  { value: 'z-image', label: 'Z-Image Turbo', group: 'Image' },
]

describe('filterOptions', () => {
  it('returns all options for an empty or blank query', () => {
    expect(filterOptions(opts, '')).toEqual(opts)
    expect(filterOptions(opts, '   ')).toEqual(opts)
  })

  it('matches case-insensitively on label', () => {
    expect(filterOptions(opts, 'WAN').map((o) => o.value)).toEqual(['wan-2.2'])
  })

  it('requires every word to match, across fields', () => {
    expect(filterOptions(opts, 'video fast').map((o) => o.value)).toEqual(['ltx-2'])
    expect(filterOptions(opts, 'ltx wan')).toEqual([])
  })

  it('matches on detail, group and value', () => {
    expect(filterOptions(opts, 'quality').map((o) => o.value)).toEqual(['wan-2.2'])
    expect(filterOptions(opts, 'image').map((o) => o.value)).toEqual(['z-image'])
    expect(filterOptions(opts, 'z-image').map((o) => o.value)).toEqual(['z-image'])
  })

  it('keeps the original order', () => {
    expect(filterOptions(opts, 'video').map((o) => o.value)).toEqual(['ltx-2', 'wan-2.2'])
  })
})

describe('nextActiveIndex', () => {
  const list: SearchableOption[] = [
    { value: 'a', label: 'A' },
    { value: 'b', label: 'B', disabled: true },
    { value: 'c', label: 'C' },
  ]

  it('moves forward and skips disabled options', () => {
    expect(nextActiveIndex(list, 0, 1)).toBe(2)
  })

  it('moves backward and skips disabled options', () => {
    expect(nextActiveIndex(list, 2, -1)).toBe(0)
  })

  it('wraps around in both directions', () => {
    expect(nextActiveIndex(list, 2, 1)).toBe(0)
    expect(nextActiveIndex(list, 0, -1)).toBe(2)
  })

  it('starts from the edges when nothing is active', () => {
    expect(nextActiveIndex(list, -1, 1)).toBe(0)
    expect(nextActiveIndex(list, -1, -1)).toBe(2)
  })

  it('returns -1 when all are disabled or the list is empty', () => {
    expect(nextActiveIndex(list.map((o) => ({ ...o, disabled: true })), 0, 1)).toBe(-1)
    expect(nextActiveIndex([], -1, 1)).toBe(-1)
  })
})
