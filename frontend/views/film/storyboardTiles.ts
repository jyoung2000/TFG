/**
 * The two pictures of a storyboard card (asked 2026-10-01: show the scene
 * remade with AI under the reference image it remakes, so the AI scenes can
 * be compared with the base images):
 *
 *   - the reference: an image shot's source photo (copied into the project
 *     as `reference_path`), or a video shot's frame of the source clip;
 *   - under it, the AI result: the rendered scene, else the AI image / frame,
 *     else the 3D capture or blockout - labelled for what it is.
 *
 * A shot made from scratch has no reference and keeps its one picture.
 */

import { filmMediaUrl } from '../../lib/film-api'
import { analysisFrameUrl, videoAnalysisApi } from '../../lib/video-analysis-api'
import type { FilmShot } from '../../types/film'

export type ReferenceSource =
  | { kind: 'project'; path: string }
  | { kind: 'analysis'; analysisId: string; shotId: string }

/** Where the lower picture comes from (see `useShotThumb`). */
export type AiSource = 'version' | 'capture' | 'frame' | 'blockout'

export function referenceSource(shot: FilmShot): ReferenceSource | null {
  if (shot.reference_path) return { kind: 'project', path: shot.reference_path }
  const ref = shot.source_ref
  if (ref?.analysis_id && ref.analysis_shot_id) return { kind: 'analysis', analysisId: ref.analysis_id, shotId: ref.analysis_shot_id }
  return null
}

export function aiTileLabel(source: AiSource | null, shot: FilmShot): string {
  switch (source) {
    case 'version':
      return 'AI scene'
    case 'frame':
      return 'AI frame'
    case 'capture':
      // An image job's capture is its AI remake; a video shot's is the 3D composer's.
      return shot.reference_path ? 'AI image' : shot.source_ref ? '3D capture' : 'Capture'
    case 'blockout':
      return '3D blockout'
    default:
      return 'Not made yet'
  }
}

/** One fetch per analysis, however many of its shots are on screen. */
const analyses = new Map<string, ReturnType<typeof videoAnalysisApi.get>>()

export async function referenceUrl(projectId: string, source: ReferenceSource): Promise<string> {
  if (source.kind === 'project') return filmMediaUrl(projectId, source.path)
  let analysis = analyses.get(source.analysisId)
  if (!analysis) {
    analysis = videoAnalysisApi.get(source.analysisId)
    analyses.set(source.analysisId, analysis)
    analysis.catch(() => analyses.delete(source.analysisId))
  }
  const shot = (await analysis).shots.find(s => s.id === source.shotId)
  const frame = shot?.frames.find(f => f.role === 'start') ?? shot?.frames[0]
  if (!frame) return ''
  return analysisFrameUrl(source.analysisId, frame.path)
}
