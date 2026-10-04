import { describe, expect, it } from 'vitest'
import { angleOptions, defaultOptions, formatBytes, groupInstalled, isValidLink } from './modelManager'
import type { InstalledModel } from './model-manager-api'
import type { LibraryModel } from '../types/models'

const GB = 1024 ** 3

describe('formatBytes', () => {
  it('formats zero, KB, MB and GB', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(512 * 1024)).toBe('512 KB')
    expect(formatBytes(5.5 * 1024 * 1024)).toBe('5.5 MB')
    expect(formatBytes(3.4 * GB)).toBe('3.4 GB')
  })
  it('handles bad input', () => {
    expect(formatBytes(-1)).toBe('0 B')
    expect(formatBytes(Number.NaN)).toBe('0 B')
  })
})

function m(id: string, kind: InstalledModel['kind'], size: number): InstalledModel {
  return { id, name: id, kind, area: 'checkpoints', size_bytes: size, shared_bytes: 0, files: [], note: '' }
}

describe('groupInstalled', () => {
  it('orders groups, merges lora kinds, sorts by size, drops empties', () => {
    const groups = groupInstalled([
      m('l1', 'lora', 5),
      m('w1', 'wangp', 10),
      m('w2', 'wangp', 30),
      m('lf', 'lora-file', 9),
      m('c1', 'component', 1),
    ])
    expect(groups.map((g) => g.title)).toEqual(['Image & video models', 'Shared components', 'LoRAs'])
    expect(groups[0].models.map((x) => x.id)).toEqual(['w2', 'w1'])
    expect(groups[2].models.map((x) => x.id)).toEqual(['lf', 'l1'])
  })
  it('returns nothing for nothing', () => {
    expect(groupInstalled([])).toEqual([])
  })
  it('puts folders under Other models', () => {
    expect(groupInstalled([m('f', 'folder', 1)])[0].title).toBe('Other models')
  })
})

function row(id: string, installed: boolean, provider = 'wangp', size: number | null = null): LibraryModel {
  return { id, name: id.toUpperCase(), provider, installed, size_gb: size } as LibraryModel
}

describe('defaultOptions', () => {
  it('lists installed first, then not installed disabled', () => {
    const opts = defaultOptions([row('a', false, 'wangp', 4.2), row('b', true, 'wangp', 8)], 'video', 'b')
    expect(opts.map((o) => o.value)).toEqual(['b', 'a'])
    expect(opts[0].group).toBe('Installed')
    expect(opts[0].disabled).toBeFalsy()
    expect(opts[0].detail).toBe('wangp · 8 GB')
    expect(opts[1]).toMatchObject({ group: 'Not installed', disabled: true, badge: 'download first' })
  })
  it('omits size when unknown', () => {
    expect(defaultOptions([row('a', true, 'native')], 'image', '')[0].detail).toBe('native')
  })
  it('always includes the current value', () => {
    const opts = defaultOptions([row('a', true)], 'image', 'gone')
    expect(opts.find((o) => o.value === 'gone')).toMatchObject({ label: 'gone' })
  })
  it('does not duplicate the current value', () => {
    expect(defaultOptions([row('a', true)], 'image', 'a')).toHaveLength(1)
  })
})

describe('angleOptions', () => {
  it('disables not-installed choices', () => {
    const opts = angleOptions([
      { id: 'x', label: 'X', installed: true },
      { id: 'y', label: 'Y', installed: false },
    ])
    const x = opts.find((o) => o.value === 'x')
    const y = opts.find((o) => o.value === 'y')
    expect(x).toMatchObject({ label: 'X' })
    expect(x?.disabled).toBeFalsy()
    expect(y).toMatchObject({ disabled: true, badge: 'not installed' })
  })
  it('offers automatic first', () => {
    expect(angleOptions([]).length).toBeGreaterThanOrEqual(1)
    expect(angleOptions([])[0].value).toBe('')
  })
})

describe('isValidLink', () => {
  it('accepts weight-file https links', () => {
    expect(isValidLink('https://example.com/a/model.safetensors')).toBe(true)
    expect(isValidLink('https://example.com/a/model.GGUF?download=true')).toBe(true)
    expect(isValidLink('https://x.org/m.ckpt')).toBe(true)
  })
  it('accepts huggingface resolve links', () => {
    expect(isValidLink('https://huggingface.co/owner/repo/resolve/main/weights')).toBe(true)
  })
  it('rejects everything else', () => {
    expect(isValidLink('http://example.com/m.safetensors')).toBe(false)
    expect(isValidLink('https://example.com/page.html')).toBe(false)
    expect(isValidLink('https://huggingface.co/owner/repo')).toBe(false)
    expect(isValidLink('not a url')).toBe(false)
    expect(isValidLink('')).toBe(false)
  })
})
