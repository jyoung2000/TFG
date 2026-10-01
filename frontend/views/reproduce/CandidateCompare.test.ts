import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ReproduceCandidate, ReproduceJob } from '../../types/reproduce'
import { CandidateCompare } from './CandidateCompare'

/* Asked 2026-10-01: the UI should make clear which image is the original and
 * which the reproduction. The compare showed "Reference" / "Best" captions only. */

const candidate = { id: 'c-1', path: 'c-1.png', round: 2, seed: 7, model: 'flux2_klein_4b', scores: { composite: 0.988, components: {}, weights_used: {}, missing: [] } } as unknown as ReproduceCandidate
const job = { id: 'rp-1', source_path: 'reference.png', reference_candidate_id: '', width: 1280, height: 720, candidates: [candidate] } as unknown as ReproduceJob

describe('CandidateCompare', () => {
  it('labels the original and the reproduction and names the model', () => {
    const html = renderToStaticMarkup(createElement(CandidateCompare, { job, candidate }))
    expect(html).toContain('data-testid="badge-original"')
    expect(html).toContain('data-testid="badge-reproduction"')
    expect(html).toContain('FLUX.2 Klein 4B')
  })
})
