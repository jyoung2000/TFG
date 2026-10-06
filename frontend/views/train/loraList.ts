/**
 * What a LoRA list row shows at a glance (user, 2026-10-02: "add a preview image
 * of the lora and time & date ... put the latest / most recent LoRA's on top").
 */
import type { LoraEntry, TrainingRun } from '../../types/training'

export type ListThumb = { kind: 'preview'; path: string } | { kind: 'sample'; runId: string; path: string } | { kind: 'none' }

/** The LoRA's own preview (its close-up) first; else the last sample of the run that made it. */
export function loraThumb(entry: Pick<LoraEntry, 'preview_paths' | 'run_id'>, runs: Pick<TrainingRun, 'id' | 'samples'>[]): ListThumb {
  const preview = entry.preview_paths?.[0]
  if (preview) return { kind: 'preview', path: preview }
  const run = runs.find(r => r.id === entry.run_id)
  const sample = run?.samples?.[run.samples.length - 1]
  if (run && sample) return { kind: 'sample', runId: run.id, path: sample.path }
  return { kind: 'none' }
}

/** A run's thumbnail: the LoRA it produced, if previewed; else its last sample. */
export function runThumb(run: Pick<TrainingRun, 'id' | 'samples' | 'lora_id'>, loras: Pick<LoraEntry, 'id' | 'preview_paths' | 'run_id'>[]): ListThumb {
  const lora = loras.find(l => l.id === run.lora_id && l.preview_paths?.length)
  if (lora?.preview_paths?.[0]) return { kind: 'preview', path: lora.preview_paths[0] }
  const sample = run.samples?.[run.samples.length - 1]
  return sample ? { kind: 'sample', runId: run.id, path: sample.path } : { kind: 'none' }
}

/** "2 Oct, 10:25 PM" - date and time, no seconds, no year unless it differs. */
export function whenLabel(ms: number, now: Date = new Date()): string {
  const d = new Date(ms)
  const sameYear = d.getFullYear() === now.getFullYear()
  const date = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }) })
  const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${date}, ${time}`
}

export function newestFirst<T extends { created_at: number }>(items: T[]): T[] {
  return [...items].sort((a, b) => b.created_at - a.created_at)
}
