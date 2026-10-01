/**
 * The 3D composer on an asset (asked 2026-10-01: use the composer in the
 * Assets tab to make consistent assets and character LoRAs). The composer
 * works on a scene + shot; an asset's studio is a stand-in shot whose cast is
 * the asset, whose scene is the asset's saved composition, and whose capture
 * (the composer's reference underlay) is the asset's first image.
 */

import type { FilmAsset, FilmScene, FilmShot } from '../../../types/film'

export const STUDIO_PREFIX = 'studio-'

export function studioScene(asset: FilmAsset): FilmScene {
  return {
    id: `${STUDIO_PREFIX}scene-${asset.id}`,
    order: 0,
    title: `${asset.name} studio`,
    description: '',
    location_id: null,
    character_ids: asset.kind === 'character' ? [asset.id] : [],
    prop_ids: asset.kind === 'prop' ? [asset.id] : [],
    shots: [],
  } as unknown as FilmScene
}

export function studioShot(asset: FilmAsset): FilmShot {
  const now = Date.now()
  return {
    id: `${STUDIO_PREFIX}${asset.id}`,
    order: 0,
    title: asset.name,
    description: asset.description ?? '',
    duration_seconds: 3,
    gap_before_seconds: null,
    transition_in: { kind: 'cut', duration_seconds: 0 },
    transition_out: { kind: 'cut', duration_seconds: 0 },
    framing: { shot_size: 'full', camera_angle: 'front', camera_elevation: 'eye', composition: 'center', fov_deg: 40, ots_shoulder: 'left', camera_mode: 'preset' },
    camera_move: 'static',
    characters: asset.kind === 'character' ? [{ asset_id: asset.id, pose_name: '', emotion: '', position_hint: '' }] : [],
    location_id: null,
    prop_ids: asset.kind === 'prop' ? [asset.id] : [],
    action: '',
    dialogue: '',
    emotion: '',
    visual_prompt: '',
    negative_prompt: '',
    prompt_locked: false,
    source_ref: null,
    composition: asset.composition ?? null,
    capture_path: asset.reference_images[0] ?? '',
    blockout_path: '',
    generation: {
      model: '', resolution: '540p', fps: 24, seed: null, aspect_ratio: '16:9', use_capture_as_reference: false,
      continue_from_previous: false, quality_preset: 'project', control_video: '', depth_video: '',
    },
    versions: [],
    current_version: null,
    status: 'draft',
    created_at: now,
    updated_at: now,
  }
}
