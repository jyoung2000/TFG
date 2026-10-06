/**
 * Every picture (or video) a list row or card has, in the order a hover walks
 * them (user, 2026-10-04: "hovering over an item with a thumbnail should cycle
 * through the pictures on that listing like a gallery or autoplay the video on
 * silent", and click a preview "to see in a big screen modal"). The first is
 * what the row shows at rest. components/HoverGallery.tsx renders them.
 */
import type { Job } from '../types/jobs'
import type { LoraEntry, TrainingRun } from '../types/training'

export interface MediaRef {
  kind: 'image' | 'video'
  /** An output path (absolute), or a file in a run's / dataset's folder. */
  path: string
  /** Set when `path` is served from a training run's folder. */
  runId?: string
  /** Set when `path` is a file of a training dataset. */
  datasetId?: string
  /** A video's still, shown until the mouse is over it. */
  poster?: string
  label?: string
}

/** The next picture, wrapping; 0 when there is nothing to walk. */
export function nextFrame(index: number, count: number): number {
  return count > 1 ? (index + 1) % count : 0
}

type RunLike = Pick<TrainingRun, 'id' | 'samples' | 'lora_id'>
type LoraLike = Pick<LoraEntry, 'preview_paths' | 'run_id'> & { id?: string }

function samplesOf(run: RunLike | undefined): MediaRef[] {
  return [...(run?.samples ?? [])].reverse().map(s => ({ kind: 'image' as const, path: s.path, runId: run!.id, label: `step ${s.step}` }))
}

/** A LoRA's preview views (labelled), else the samples of the run that made it, newest first. */
export function loraGallery(entry: LoraLike, runs: RunLike[], labels: readonly string[] = []): MediaRef[] {
  const previews = entry.preview_paths ?? []
  if (previews.length) return previews.map((path, i) => ({ kind: 'image' as const, path, ...(labels[i] ? { label: labels[i] } : {}) }))
  return samplesOf(runs.find(r => r.id === entry.run_id))
}

/** A run's LoRA preview once rendered, then its samples newest first. */
export function runGallery(run: RunLike, loras: LoraLike[], labels: readonly string[] = []): MediaRef[] {
  const lora = loras.find(l => l.id === run.lora_id && l.preview_paths?.length)
  const previews = lora ? loraGallery(lora, [], labels) : []
  return [...previews, ...samplesOf(run)]
}

/** A History job's images and videos; a training run's samples, newest first. */
export function jobGallery(job: Pick<Job, 'kind' | 'outputs' | 'metrics'>): MediaRef[] {
  const media = job.outputs.filter(o => o.kind === 'image' || o.kind === 'video').map((o): MediaRef =>
    o.kind === 'video' ? { kind: 'video', path: o.path, ...(o.thumb ? { poster: o.thumb } : {}) } : { kind: 'image', path: o.thumb || o.path })
  if (media.length) return job.kind === 'training' ? media.reverse() : media
  const samples = job.metrics?.samples
  if (job.kind === 'training' && Array.isArray(samples)) {
    return samples.filter((s): s is string => typeof s === 'string' && !!s).reverse().map(path => ({ kind: 'image' as const, path }))
  }
  return []
}
