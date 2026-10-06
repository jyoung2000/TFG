import { describe, expect, it } from 'vitest'
import { filterAssets, findMentions, insertMention, mentionQuery } from './assetMentions'

describe('mentionQuery', () => {
  it('finds the @ token at the caret', () => {
    expect(mentionQuery('Hi @Rav', 7)).toEqual({ start: 3, query: 'Rav' })
    expect(mentionQuery('@', 1)).toEqual({ start: 0, query: '' })
    expect(mentionQuery('(@Raven QA', 10)).toEqual({ start: 1, query: 'Raven QA' })
  })
  it('ignores emails, newlines and long queries', () => {
    expect(mentionQuery('me@host', 7)).toBeNull()
    expect(mentionQuery('@a\nb', 4)).toBeNull()
    expect(mentionQuery('@' + 'x'.repeat(41), 42)).toBeNull()
    expect(mentionQuery('no mention', 5)).toBeNull()
  })
})

describe('filterAssets', () => {
  const assets = [
    { name: 'Dark Raven', kind: 'character' },
    { name: 'Raven QA', kind: 'character' },
    { name: 'Lantern', kind: 'prop' },
  ]
  it('puts prefix matches before substring matches, case-insensitively', () => {
    expect(filterAssets(assets, 'raven').map(a => a.name)).toEqual(['Raven QA', 'Dark Raven'])
    expect(filterAssets(assets, '').length).toBe(3)
  })
  it('caps at 8', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ name: `A${i}`, kind: 'prop' }))
    expect(filterAssets(many, 'a')).toHaveLength(8)
  })
})

describe('insertMention', () => {
  it('replaces the token and moves the caret past the trailing space', () => {
    expect(insertMention('Hi @Rav there', 3, 7, 'Raven QA')).toEqual({ text: 'Hi @Raven QA  there', caret: 13 })
  })
})

describe('findMentions', () => {
  const names = ['Raven', 'Raven QA', 'Lantern']
  it('matches longest name first, case-insensitively', () => {
    expect(findMentions('@raven qa walks', names)).toEqual(['Raven QA'])
    expect(findMentions('@Raven walks', names)).toEqual(['Raven'])
  })
  it('treats underscore as a space and requires a boundary', () => {
    expect(findMentions('@Raven_QA.', names)).toEqual(['Raven QA'])
    expect(findMentions('@Ravens', names)).toEqual([])
    expect(findMentions('a @Lantern, @Raven', names)).toEqual(['Raven', 'Lantern'])
  })
})
