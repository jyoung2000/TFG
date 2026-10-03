/**
 * Thumbs up / thumbs down on what the app makes (backend film/taste.py).
 * User, 2026-10-03: "Let the user grade prompts, styleguides, videos, and images
 * the software creates with a simple thumbs up and thumbs down ... so the
 * software can generate to the users taste and preference".
 */
import { backendFetch } from './backend'
import type { Job } from '../types/jobs'

export type TasteKind = 'lora' | 'prompt' | 'style_guide' | 'image' | 'video'
export type Vote = 1 | -1

export interface TasteVote {
  kind: TasteKind
  subject: string
  vote: Vote
  file: string
  project_id: string
  prompt: string
  model: string
  loras: string[]
  meta: Record<string, string | number | boolean>
  created_at: number
  updated_at: number
}

export interface TastePhrase { text: string; up: number; down: number }

export interface TasteSummary {
  enabled: boolean
  votes: number
  up: number
  down: number
  liked_phrases: TastePhrase[]
  disliked_phrases: TastePhrase[]
  liked_loras: string[]
  disliked_loras: string[]
  training: { resolution: number; steps: number; batch_size: number; liked: number } | null
}

/** What a vote is about and what made it. */
export interface TasteTarget {
  kind: TasteKind
  subject: string
  projectId?: string
  prompt?: string
  model?: string
  loras?: string[]
}

export const voteKey = (kind: TasteKind, subject: string) => `${kind}\u0000${subject}`

/** Clicking the thumb already chosen takes the vote back. */
export function nextVote(current: Vote | 0, clicked: Vote): Vote | 0 {
  return current === clicked ? 0 : clicked
}

/** A finished History job's image or video, ready to grade; null for anything else. */
export function jobTasteTarget(job: Job): TasteTarget | null {
  if (job.status !== 'complete') return null
  const output = job.outputs.find(o => o.kind === 'image' || o.kind === 'video')
  if (!output) return null
  const loras = Array.isArray(job.params?.loras)
    ? (job.params.loras as unknown[]).map(l => (l && typeof l === 'object' && 'name' in l ? String((l as { name: unknown }).name) : '')).filter(Boolean)
    : []
  return { kind: output.kind === 'video' ? 'video' : 'image', subject: output.path, prompt: job.prompt, model: job.model, loras, projectId: job.project_id || undefined }
}

/** The Train speed whose preset matches the training settings of the LoRAs liked most. */
export function speedForTaste(training: TasteSummary['training']): 'fast' | 'balanced' | 'standard' | null {
  if (!training) return null
  if (training.batch_size === 2 && training.steps === 150) return 'fast'
  if (training.batch_size === 2 && training.steps === 300) return 'balanced'
  if (training.batch_size <= 1) return 'standard'
  return null
}

/** Liked phrases not already in the prompt, to add with one click. */
export function tasteChips(liked: TastePhrase[], prompt: string, max = 6): string[] {
  const have = prompt.toLowerCase()
  return liked.map(p => p.text).filter(text => !have.includes(text)).slice(0, max)
}

/** The prompt with a phrase added on the end, comma-separated. */
export function appendPhrase(prompt: string, phrase: string): string {
  const trimmed = prompt.trim().replace(/[,\s]+$/, '')
  return trimmed ? `${trimmed}, ${phrase}` : phrase
}

/** Liked first, disliked last, otherwise as they came. */
export function byTaste<T>(items: T[], voteOf: (item: T) => Vote | 0): T[] {
  return items.map((item, index) => ({ item, index, vote: voteOf(item) }))
    .sort((a, b) => b.vote - a.vote || a.index - b.index)
    .map(entry => entry.item)
}

// ---- API ------------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await backendFetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) throw new Error((await response.text().catch(() => '')) || `Request failed (${response.status})`)
  return (await response.json()) as T
}

export const tasteApi = {
  vote: (target: TasteTarget, vote: Vote | 0) =>
    request<{ vote: TasteVote | null }>('/api/taste/vote', {
      method: 'POST',
      body: JSON.stringify({ kind: target.kind, subject: target.subject, vote, project_id: target.projectId ?? '', prompt: target.prompt ?? '', model: target.model ?? '', loras: target.loras ?? [] }),
    }),
  votes: () => request<{ votes: TasteVote[] }>('/api/taste/votes'),
  summary: () => request<TasteSummary>('/api/taste/summary'),
}

// ---- one shared cache, so every thumb on screen agrees ----------------------

type Listener = () => void
const votes = new Map<string, Vote>()
const listeners = new Set<Listener>()
let loading: Promise<void> | null = null
let version = 0

function emit() {
  version += 1
  listeners.forEach(l => l())
}

export const tasteStore = {
  subscribe(listener: Listener) {
    listeners.add(listener)
    return () => { listeners.delete(listener) }
  },
  version: () => version,
  get: (kind: TasteKind, subject: string): Vote | 0 => votes.get(voteKey(kind, subject)) ?? 0,
  load(): Promise<void> {
    loading ??= tasteApi.votes().then(({ votes: all }) => {
      all.forEach(v => votes.set(voteKey(v.kind, v.subject), v.vote))
      emit()
    }).catch(() => { loading = null })
    return loading
  },
  async set(target: TasteTarget, vote: Vote | 0): Promise<void> {
    const key = voteKey(target.kind, target.subject)
    const before = votes.get(key)
    if (vote === 0) votes.delete(key)
    else votes.set(key, vote)
    emit()
    try {
      await tasteApi.vote(target, vote)
    } catch (error) {
      if (before === undefined) votes.delete(key)
      else votes.set(key, before)
      emit()
      throw error
    }
  },
}
