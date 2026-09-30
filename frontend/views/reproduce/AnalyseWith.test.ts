/** "Analyse with" - which vision models may be chosen.

The list is the real response from the audit machine (12 models, 7 of them
image-capable), so the test pins the two behaviours that matter: an image-capable
model is offered, and a text-only model is *shown and marked* rather than
hidden - the user can see what they have and why it is not on offer.
*/

import { describe, expect, it } from 'vitest'

import { partitionVisionModels, type VisionModelEntry } from './AnalyseWith'

function m(over: Partial<VisionModelEntry> & { id: string }): VisionModelEntry {
  return {
    name: over.id,
    provider: 'ollama',
    size_gb: null,
    can_analyse_images: false,
    detail: 'completion',
    ...over,
  }
}

const REAL: VisionModelEntry[] = [
  m({ id: 'qwen2.5vl:7b', size_gb: 6.0, can_analyse_images: true, detail: 'completion, vision' }),
  m({ id: 'llava:7b', size_gb: 4.7, can_analyse_images: true, detail: 'completion, vision' }),
  m({ id: 'llava:13b', size_gb: 8.0, can_analyse_images: true, detail: 'completion, vision' }),
  m({ id: 'llama3.2-vision:latest', size_gb: 7.8, can_analyse_images: true, detail: 'tools, completion, vision' }),
  m({ id: 'moondream:1.8b', size_gb: 1.7, can_analyse_images: true, detail: 'completion, vision' }),
  m({ id: 'gemma4:12b', size_gb: 7.6, can_analyse_images: true, detail: 'completion, vision, audio, tools' }),
  m({ id: 'qwen2.5:3b', size_gb: 1.9, detail: 'completion, tools' }),
  m({ id: 'qwen2.5:14b', size_gb: 9.0, detail: 'completion, tools' }),
  m({ id: 'llama3.2:3b', size_gb: 2.0, detail: 'completion, tools' }),
]

describe('partitionVisionModels', () => {
  it('offers every image-capable model and no text-only one', () => {
    const { usable, textOnly } = partitionVisionModels(REAL)
    expect(usable.map(x => x.id)).toEqual([
      'qwen2.5vl:7b',
      'llava:7b',
      'llava:13b',
      'llama3.2-vision:latest',
      'moondream:1.8b',
      'gemma4:12b',
    ])
    expect(textOnly.map(x => x.id)).toEqual(['qwen2.5:3b', 'qwen2.5:14b', 'llama3.2:3b'])
  })

  it('labels a model with its size', () => {
    expect(partitionVisionModels(REAL).usable[0].label).toBe('qwen2.5vl:7b · 6 GB')
  })

  it('says a text-only model cannot read an image, instead of hiding it', () => {
    const { textOnly } = partitionVisionModels(REAL)
    expect(textOnly[0].label).toContain('text only')
    expect(textOnly[0].label).toContain('cannot read an image')
  })

  it('never offers a text-only model as a choice', () => {
    // The failure this guards: a model that silently falls back to CLIP tags
    // while the UI claimed it was reading the picture.
    const { usable } = partitionVisionModels([m({ id: 'qwen2.5:3b' })])
    expect(usable).toEqual([])
  })

  it('handles an empty list, e.g. the provider is unreachable', () => {
    expect(partitionVisionModels([])).toEqual({ usable: [], textOnly: [] })
  })
})
