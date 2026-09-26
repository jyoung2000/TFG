import { describe, expect, it } from 'vitest'
import { PROMPT_STYLES, SPEC_TARGETS } from '../../types/shotspec'
import { mergeSpecs, sectionsThatWouldChange } from './fusion'
import { previewPrompt } from './formatters'
import { attributeKeys, editSection, emptySpec, toggleLock } from './schema'

function sample() {
  const spec = emptySpec('image')
  spec.source = { ...spec.source, path: '/ref.jpg', width: 1280, height: 720, aspect: '16:9', hash: 'abc' }
  spec.subjects = [{ label: 'person', bbox: [0.3, 0.2, 0.4, 0.7], depth_median: 0.7, count: 2, attributes: [] }]
  spec.camera = { ...spec.camera, shot_size: 'medium', angle: 'front', height: 'eye', move: 'push_in', move_intensity: 0.5 }
  spec.lighting = { key_direction: 'window', quality: 'soft', color_temp: 'warm', mood: 'calm' }
  spec.style = { tags: [{ term: 'cinematic', score: 0.3 }, { term: 'film still', score: 0.28 }], medium: 'photo', artists: [], negatives: ['blurry'] }
  spec.measured = { ...spec.measured, palette: [{ hex: '#3a2a20', share: 0.6 }, { hex: '#e6be78', share: 0.4 }] }
  spec.narrative = { what_happens: 'two people talk at a console', purpose: '', beat: '' }
  spec.provenance = { subjects: 'florence', camera: 'florence', style: 'clip', measured: 'measured' }
  return spec
}

describe('shotspec preview formatters', () => {
  it('produces a non-empty prompt for every target × style (negative_only excepted)', () => {
    const spec = sample()
    for (const target of SPEC_TARGETS) {
      for (const style of PROMPT_STYLES) {
        const { prompt, negative_prompt } = previewPrompt(spec, target, style)
        if (style === 'negative_only') expect(prompt).toBe('')
        else expect(prompt.length, `${target}/${style}`).toBeGreaterThan(20)
        expect(negative_prompt).toContain('blurry')
      }
    }
  })

  it('drops motion for still targets and keeps it for video', () => {
    const spec = sample()
    expect(previewPrompt(spec, 'z_image', 'narrative').prompt).not.toContain('push in')
    expect(previewPrompt(spec, 'ltx2', 'narrative').prompt).toContain('push in')
  })

  it('is deterministic and applies hints to the style block', () => {
    const spec = sample()
    expect(previewPrompt(spec, 'ltx2', 'narrative')).toEqual(previewPrompt(spec, 'ltx2', 'narrative'))
    const hinted = previewPrompt(spec, 'ltx2', 'narrative', ['anamorphic lens flare'])
    expect(hinted.prompt).toContain('anamorphic lens flare')
  })

  it('weighted style emphasises subjects', () => {
    expect(previewPrompt(sample(), 'sdxl', 'weighted').prompt).toContain('(2 person:1.2)')
  })
})

describe('shotspec schema helpers', () => {
  it('derives stable attribute keys', () => {
    const keys = attributeKeys(sample())
    expect(keys).toContain('camera.shot_size=medium')
    expect(keys).toContain('style.tag=cinematic')
    expect(keys).toContain('subjects.count=2')
    expect(keys).toEqual([...keys].sort())
  })

  it('locks a section on edit and protects it from merges', () => {
    const base = editSection(sample(), 'camera', { ...sample().camera, shot_size: 'closeup' })
    expect(base.locks.camera).toBe(true)
    expect(base.provenance.camera).toBe('user')
    const update = sample()
    update.camera.shot_size = 'wide'
    update.style.tags = [{ term: 'noir', score: 0.9 }]
    update.provenance = { camera: 'florence', style: 'clip' }
    const merged = mergeSpecs(base, update)
    expect(merged.camera.shot_size).toBe('closeup')
    expect(merged.style.tags[0].term).toBe('noir')
    expect(sectionsThatWouldChange(base, update)).toEqual(['style'])
    expect(toggleLock(merged, 'camera').locks.camera).toBe(false)
  })
})
