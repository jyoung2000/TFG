/**
 * What the Activity panel shows beside the render queue (2026-10-02: a LoRA
 * training run never appeared there - the panel read only the image/video
 * queue). Active jobs of every other kind: training, downloads, analysis,
 * reproduce, 3D scenes. Image and video renders come from the queue already.
 */
import { JOB_KIND_LABEL, type Job } from '../types/jobs'

const FROM_THE_QUEUE = new Set(['image_gen', 'video_gen'])

export function backgroundJobs(jobs: Job[]): Job[] {
  return jobs.filter(j => (j.status === 'running' || j.status === 'queued') && !FROM_THE_QUEUE.has(j.kind))
}

/** The collapsed chip's words for the first background job, e.g. "Training 12%". */
export function backgroundLabel(jobs: Job[]): string {
  const first = jobs[0]
  if (!first) return ''
  const more = jobs.length > 1 ? ` +${jobs.length - 1}` : ''
  return `${JOB_KIND_LABEL[first.kind]} ${Math.round(first.progress)}%${more}`
}
