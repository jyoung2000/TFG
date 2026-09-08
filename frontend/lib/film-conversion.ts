/**
 * "Edit in Film Maker": turn an already-rendered host clip (Quick Mode result,
 * Gen Space asset, timeline clip) into a film shot whose version 1 is that
 * clip — nothing is re-encoded, the file is referenced as-is. Shared by every
 * entry point so the conversion rules live in one place.
 */

import { filmApi } from './film-api'
import type { Asset, GenerationParams } from '../types/project'

export interface FilmConversionSource {
  /** Absolute path of the rendered video (already inside the project's asset folder when possible). */
  outputPath: string
  prompt: string
  negativePrompt?: string
  model?: string
  resolution?: string
  durationSeconds?: number
  fps?: number
  seed?: number | null
  aspectRatio?: string
  cameraMotion?: string
  mode?: string
  inputImagePath?: string
  title?: string
  projectName?: string
}

export interface FilmConversionResult {
  sceneId: string
  shotId: string
  versionNumber: number
}

/** Map a host asset's generation record onto the conversion request. */
export function conversionSourceFromAsset(asset: Asset, params?: GenerationParams): FilmConversionSource {
  const generation = params ?? asset.generationParams
  return {
    outputPath: asset.path,
    prompt: generation?.prompt || asset.prompt || 'Imported clip',
    model: generation?.model,
    resolution: generation?.resolution || asset.resolution,
    durationSeconds: generation?.duration ?? asset.duration,
    fps: generation?.fps,
    seed: null,
    aspectRatio: generation?.imageAspectRatio,
    cameraMotion: generation?.cameraMotion,
    mode: generation?.mode,
    inputImagePath: generation?.inputImageUrl?.startsWith('file://') ? generation.inputImageUrl.slice(7) : undefined,
  }
}

/** Import the clip into the given project's film facet as a new scene/shot. */
export async function importClipAsShot(projectId: string, source: FilmConversionSource): Promise<FilmConversionResult> {
  const result = await filmApi.importGeneration(projectId, {
    prompt: source.prompt,
    negative_prompt: source.negativePrompt ?? '',
    output_path: source.outputPath,
    model: source.model ?? '',
    resolution: source.resolution ?? '',
    duration_seconds: source.durationSeconds ?? 4,
    fps: source.fps ?? 24,
    seed: source.seed ?? null,
    aspect_ratio: source.aspectRatio ?? '16:9',
    camera_motion: source.cameraMotion,
    mode: source.mode ?? 'text-to-video',
    input_image_path: source.inputImagePath,
    title: source.title ?? 'Shot 1',
    project_name: source.projectName,
  })
  return { sceneId: result.scene_id, shotId: result.shot_id, versionNumber: result.version_number }
}
