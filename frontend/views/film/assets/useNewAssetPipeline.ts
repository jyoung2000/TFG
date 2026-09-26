/**
 * The "New asset" wizard's state machine: a client-side sequencing of
 * existing endpoints (create → attach seed → style guide → turnaround or
 * sample looks). No new pipeline endpoint; the backend store stays the
 * single source of truth — after every call the film store is refreshed
 * and the wizard reads the asset from it.
 */

import { useCallback, useRef, useState } from 'react'
import { useFilm } from '../../../contexts/FilmContext'
import { filmApi } from '../../../lib/film-api'
import type { FilmAssetKind } from '../../../types/film'

export type StepId = 'source' | 'guide' | 'renders'
export type StepStatus = 'pending' | 'running' | 'done' | 'error'

export interface PipelineStep {
  id: StepId
  status: StepStatus
  error: string
  /** "n/4" while the style branch renders its sample looks. */
  progress: string
}

export interface PipelineInput {
  kind: FilmAssetKind
  name: string
  /** A picked seed image, or a text prompt to generate one from. */
  seed: { imageBase64: string; fileName: string } | { prompt: string }
}

/** Fixed, varied subjects for the style branch's four sample looks. */
export const STYLE_SAMPLE_SUBJECTS = [
  'portrait, shallow depth',
  'wide landscape',
  'interior, practical lights',
  'night exterior',
]

const fresh = (): PipelineStep[] =>
  (['source', 'guide', 'renders'] as StepId[]).map(id => ({ id, status: 'pending', error: '', progress: '' }))

export function useNewAssetPipeline() {
  const { film, refresh } = useFilm()
  const [assetId, setAssetId] = useState<string | null>(null)
  const [steps, setSteps] = useState<PipelineStep[]>(fresh())
  const [running, setRunning] = useState(false)
  const inputRef = useRef<PipelineInput | null>(null)

  const mark = useCallback((id: StepId, patch: Partial<PipelineStep>) => {
    setSteps(current => current.map(s => (s.id === id ? { ...s, ...patch } : s)))
  }, [])

  const execute = useCallback(async (input: PipelineInput, resume: PipelineStep[], startId: string | null) => {
    if (!film) return
    const done = new Set(resume.filter(s => s.status === 'done').map(s => s.id))
    let id = startId
    setRunning(true)
    const step = async (stepId: StepId, work: () => Promise<void>) => {
      if (done.has(stepId)) return
      mark(stepId, { status: 'running', error: '' })
      try {
        await work()
        await refresh()
        mark(stepId, { status: 'done' })
      } catch (e) {
        mark(stepId, { status: 'error', error: e instanceof Error ? e.message : String(e) })
        throw e
      }
    }
    try {
      await step('source', async () => {
        if (!id) {
          const count = film.assets.filter(a => a.kind === input.kind).length
          const asset = await filmApi.createAsset(film.id, { kind: input.kind, name: input.name.trim() || `${input.kind} ${count + 1}` })
          id = asset.id
          setAssetId(asset.id)
        }
        if ('imageBase64' in input.seed) await filmApi.addAssetReference(film.id, id, input.seed.imageBase64, input.seed.fileName)
        else await filmApi.generateAssetReference(film.id, id, input.seed.prompt)
      })
      await step('guide', async () => {
        if (!id) throw new Error('No asset yet')
        await filmApi.generateAssetStyleGuide(film.id, id)
      })
      await step('renders', async () => {
        if (!id) throw new Error('No asset yet')
        if (input.kind === 'style') {
          // The style guide already wrote the asset's style_prompt; apply the
          // look across four fixed subjects so the user sees it in context.
          const project = await filmApi.getProject(film.id)
          const stylePrompt = project.assets.find(a => a.id === id)?.style_prompt ?? ''
          for (let i = 0; i < STYLE_SAMPLE_SUBJECTS.length; i++) {
            mark('renders', { progress: `${i}/4` })
            await filmApi.generateAssetReference(film.id, id, `${STYLE_SAMPLE_SUBJECTS[i]}${stylePrompt ? `, ${stylePrompt}` : ''}`)
          }
          mark('renders', { progress: '4/4' })
        } else {
          await filmApi.referenceSheet(film.id, id)
        }
      })
    } catch {
      // The failed step already carries its error; earlier steps stay done.
    } finally {
      setRunning(false)
    }
  }, [film, mark, refresh])

  const run = useCallback(async (input: PipelineInput) => {
    inputRef.current = input
    const clean = fresh()
    setSteps(clean)
    await execute(input, clean, assetId)
  }, [execute, assetId])

  /** Re-run from the first step that is not done, keeping what succeeded. */
  const retry = useCallback(async () => {
    const input = inputRef.current
    if (!input) return
    setSteps(current => current.map(s => (s.status === 'error' ? { ...s, status: 'pending', error: '' } : s)))
    await execute(input, steps.map(s => (s.status === 'error' ? { ...s, status: 'pending' } : s)), assetId)
  }, [execute, steps, assetId])

  /** Backing out entirely deletes the partially built asset. */
  const discard = useCallback(async () => {
    if (film && assetId) {
      try { await filmApi.deleteAsset(film.id, assetId); await refresh() } catch { /* already gone */ }
    }
    setAssetId(null)
    setSteps(fresh())
    inputRef.current = null
  }, [film, assetId, refresh])

  const reset = useCallback(() => {
    setAssetId(null)
    setSteps(fresh())
    inputRef.current = null
  }, [])

  return { assetId, steps, running, run, retry, discard, reset }
}
