/**
 * The image a History card previews (2026-10-02): the first output that is an
 * image or has a thumbnail - a finished LoRA run's first output is its
 * .safetensors - else, while a training run is going, its latest sample.
 */
import type { Job } from '../../types/jobs'

export function jobPreview(job: Pick<Job, 'outputs' | 'metrics'> & { kind?: Job['kind'] }): { source: string; kind: 'image' | 'video' | 'file' | null } {
  // A training run lists its samples oldest first; the newest shows what it learned.
  const candidates = job.outputs.filter(o => o.thumb || o.kind === 'image')
  const shown = job.kind === 'training' ? candidates[candidates.length - 1] : candidates[0]
  if (shown) return { source: shown.thumb || shown.path, kind: shown.kind }
  const samples = job.metrics?.samples
  if (Array.isArray(samples) && samples.length > 0) {
    const last: unknown = samples[samples.length - 1]
    if (typeof last === 'string' && last) return { source: last, kind: 'image' }
  }
  return { source: '', kind: job.outputs[0]?.kind ?? null }
}
