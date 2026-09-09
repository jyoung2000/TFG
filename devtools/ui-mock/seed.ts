/**
 * The demo film the UI-only mode opens on.
 *
 * Chosen to exercise the screens rather than to be minimal: several scenes,
 * every asset kind, a composed shot with a capture, a shot with a completed
 * render, a failed version with a retry path, continuity that is deliberately
 * imperfect, and a script. Everything is typed against the renderer's own
 * `FilmProject`, so a schema change fails `pnpm typecheck` here first.
 */

import type {
  CameraAngle,
  CameraMove,
  CompositionId,
  CompositionScene,
  FilmAsset,
  FilmAssetKind,
  FilmProject,
  FilmScene,
  FilmShot,
  ShotSize,
  ShotVersion,
} from '../../frontend/types/film'
import type { AppSettings } from '../../frontend/types/settings'

const T0 = Date.UTC(2026, 2, 14, 9, 0, 0)
let clock = T0
/** Deterministic, monotonic timestamps keep snapshots and ordering stable. */
const stamp = () => (clock += 1000)

export const DEMO_PROJECT_ID = 'ui-mock-film'
/** Relative path the mock serves a rendered clip for; see routes/media.ts. */
export const DEMO_OUTPUT = 'ui-mock/renders/scene-1-shot-2-v1.mp4'

function asset(kind: FilmAssetKind, id: string, name: string, fields: Partial<FilmAsset> = {}): FilmAsset {
  return {
    id,
    kind,
    name,
    description: '',
    appearance: '',
    wardrobe: '',
    accessories: '',
    environment: '',
    lighting: '',
    atmosphere: '',
    time_of_day: '',
    prop_details: '',
    style_prompt: '',
    continuity_notes: '',
    reference_images: [],
    created_at: stamp(),
    updated_at: stamp(),
    ...fields,
  }
}

function shot(
  id: string,
  order: number,
  title: string,
  fields: Partial<FilmShot> & {
    shot_size?: ShotSize
    camera_angle?: CameraAngle
    composition?: CompositionScene | null
  } = {},
): FilmShot {
  const { shot_size, camera_angle, ...rest } = fields
  return {
    id,
    order,
    title,
    description: '',
    duration_seconds: 5,
    gap_before_seconds: null,
    framing: {
      shot_size: shot_size ?? 'medium',
      camera_angle: camera_angle ?? 'front',
      camera_elevation: 'eye',
      composition: 'center',
      fov_deg: 40,
      ots_foreground_id: null,
      ots_subject_id: null,
      ots_shoulder: 'right',
      camera_mode: 'preset',
    },
    camera_move: 'static',
    characters: [],
    location_id: null,
    prop_ids: [],
    action: '',
    dialogue: '',
    emotion: '',
    visual_prompt: '',
    negative_prompt: '',
    prompt_locked: false,
    composition: null,
    capture_path: '',
    generation: {
      model: '',
      resolution: '',
      fps: 24,
      seed: null,
      aspect_ratio: '16:9',
      use_capture_as_reference: true,
      continue_from_previous: false,
      quality_preset: 'project',
    },
    versions: [],
    current_version: null,
    status: 'draft',
    created_at: stamp(),
    updated_at: stamp(),
    ...rest,
  }
}

function scene(id: string, order: number, title: string, fields: Partial<FilmScene> = {}): FilmScene {
  return {
    id,
    order,
    title,
    description: '',
    location_id: null,
    character_ids: [],
    prop_ids: [],
    mood: '',
    lighting: '',
    time_of_day: '',
    continuity_notes: '',
    inter_shot_gap_seconds: null,
    shots: [],
    ...fields,
  }
}

function version(number: number, fields: Partial<ShotVersion> = {}): ShotVersion {
  return {
    number,
    kind: 'preview',
    status: 'complete',
    prompt: '',
    negative_prompt: '',
    model: 'fast',
    resolution: '960x540',
    fps: 24,
    duration_seconds: 5,
    seed: 424242,
    capture_path: '',
    output_path: '',
    error: '',
    wardrobe_snapshot: {},
    shot_snapshot: {},
    generation_seconds: 41.2,
    gpu_name: 'NVIDIA GeForce RTX 4070',
    peak_vram_gb: 9.4,
    execution_mode: 'wangp',
    created_at: stamp(),
    ...fields,
  }
}

/** A small composition so the Shot Composer opens on something to look at. */
function composition(
  shotSize: ShotSize,
  angle: CameraAngle,
  comp: CompositionId,
  move: CameraMove,
  duration: number,
): CompositionScene {
  return {
    objects: [
      {
        id: 'obj-mara',
        name: 'Mara',
        type: 'figure',
        asset_id: 'asset-mara',
        visible: true,
        locked: false,
        transform: { position: [0, 0, 0], rotation: [0, 0.35, 0], scale: [1, 1, 1] },
        pose: {},
        figure_variant: 'female',
        color: '#8b5cf6',
        keyframes: [],
        fov: null,
      },
      {
        id: 'obj-crate',
        name: 'Supply crate',
        type: 'cube',
        asset_id: 'asset-crate',
        visible: true,
        locked: false,
        transform: { position: [1.4, 0.3, -0.6], rotation: [0, 0.2, 0], scale: [0.6, 0.6, 0.6] },
        pose: {},
        figure_variant: 'male',
        color: '#a8a29e',
        keyframes: [],
        fov: null,
      },
    ],
    camera: {
      id: 'camera',
      name: 'Shot Camera',
      type: 'camera',
      asset_id: null,
      visible: true,
      locked: false,
      transform: { position: [0.8, 1.6, 3.4], rotation: [-0.05, 0.18, 0], scale: [1, 1, 1] },
      pose: {},
      figure_variant: 'male',
      color: '#ffffff',
      keyframes: [],
      fov: 40,
    },
    framing: {
      shot_size: shotSize,
      camera_angle: angle,
      camera_elevation: 'eye',
      composition: comp,
      fov_deg: 40,
      ots_foreground_id: null,
      ots_subject_id: null,
      ots_shoulder: 'right',
      camera_mode: 'preset',
    },
    camera_move: move,
    duration_seconds: duration,
  }
}

const SCRIPT = `INT. RELAY STATION - NIGHT

Snow ticks against the window. MARA (30s, field engineer) works a
dead console by torchlight.

MARA
Say something. Anything.

The console answers with one line of text. She stops breathing.

EXT. RIDGE - DAWN

Mara climbs out into blue light. Below her, the valley is empty —
and the antenna is still turning.

MARA
Somebody is still pointing it.
`

/** Project defaults a brand-new film starts from, matching the backend. */
function baseProject(id: string, name: string): FilmProject {
  return {
    schema_version: 4,
    id,
    name: name || 'Untitled film',
    script: { content: '', updated_at: stamp() },
    settings: {
      default_model: 'fast',
      default_resolution: '1280x720',
      style_prompt: '',
      default_negative_prompt: '',
      inter_shot_gap_seconds: 0.25,
      strict_continuity: false,
      default_quality_preset: 'balanced',
      preview_resolution: '960x540',
      preview_max_seconds: 4,
      media_provider: '',
      video_model: '',
      image_model: '',
    },
    assets: [],
    scenes: [],
    pose_library: [],
    created_at: Date.now(),
    updated_at: Date.now(),
  }
}

/**
 * A new film is empty, exactly as it is in the app — only the well-known demo
 * id gets the seeded story, so "New film" behaves the way it really does.
 */
export function emptyProject(id: string, name = ''): FilmProject {
  return baseProject(id, name)
}

export function seedProject(id: string = DEMO_PROJECT_ID, name = ''): FilmProject {
  const assets: FilmAsset[] = [
    asset('character', 'asset-mara', 'Mara', {
      description: 'Field engineer, mid-thirties, dry and unhurried.',
      appearance: 'Short dark hair, weathered face, a burn scar along the left thumb.',
      wardrobe: 'Grey thermal jacket, orange harness, heavy gloves.',
      accessories: 'Head torch, multi-tool on a lanyard.',
      continuity_notes: 'Harness always clipped on the left hip.',
    }),
    asset('character', 'asset-idris', 'Idris', {
      description: 'Relay operator. Talks more than he should.',
      appearance: 'Tall, close-cropped beard, wire-rim glasses.',
      wardrobe: 'Navy fleece over a station jumpsuit.',
    }),
    asset('location', 'asset-station', 'Relay Station', {
      description: 'A two-room hut buried to the windows in snow.',
      environment: 'Cramped interior, cable runs, a console wall of dead screens.',
      lighting: 'Torchlight and one failing amber strip.',
      atmosphere: 'Cold, close, humming.',
      time_of_day: 'night',
    }),
    asset('location', 'asset-ridge', 'The Ridge', {
      description: 'An exposed spine of rock above the valley.',
      environment: 'Wind-scoured snow, a lattice antenna turning slowly.',
      lighting: 'Flat blue pre-dawn.',
      atmosphere: 'Vast and silent.',
      time_of_day: 'dawn',
    }),
    asset('prop', 'asset-crate', 'Supply crate', {
      prop_details: 'Scuffed polymer case, stencilled number 47.',
    }),
    asset('style', 'asset-style', 'House look', {
      style_prompt: 'anamorphic 35mm, halation on practicals, muted teal and amber, fine grain',
    }),
  ]

  const scene1 = scene('scene-1', 1, 'Relay station, night', {
    description: 'Mara wakes the console and gets an answer she did not expect.',
    location_id: 'asset-station',
    character_ids: ['asset-mara'],
    prop_ids: ['asset-crate'],
    mood: 'tense, quiet',
    lighting: 'torchlight, failing amber strip',
    time_of_day: 'night',
    shots: [
      shot('shot-1-1', 1, 'Station exterior', {
        shot_size: 'xwide',
        description: 'The hut, almost buried, one window lit.',
        action: 'Snow moves across the frame in sheets.',
        location_id: 'asset-station',
        camera_move: 'push_in',
        duration_seconds: 6,
        status: 'ready',
        visual_prompt:
          'Extreme wide shot of a snow-buried relay hut at night, single amber window, drifting snow, anamorphic 35mm, halation, muted teal',
      }),
      shot('shot-1-2', 2, 'Mara at the console', {
        shot_size: 'medium',
        camera_angle: 'threeQuarterLeft',
        description: 'Torch in her teeth, hands in the console guts.',
        action: 'She strips a wire and touches it to the board.',
        dialogue: 'Say something. Anything.',
        emotion: 'focused',
        location_id: 'asset-station',
        prop_ids: ['asset-crate'],
        characters: [
          { asset_id: 'asset-mara', pose_name: 'crouch', emotion: 'focused', position_hint: 'centre frame' },
        ],
        camera_move: 'push_in',
        status: 'approved',
        capture_path: 'captures/shot-1-2.png',
        composition: composition('medium', 'threeQuarterLeft', 'leftThird', 'push_in', 5),
        current_version: 1,
        visual_prompt:
          'Medium three-quarter shot of a field engineer crouched at an open console, torchlight on her face, cable runs behind, anamorphic 35mm, halation, muted teal and amber',
        versions: [
          version(1, {
            prompt: 'Medium three-quarter shot of a field engineer crouched at an open console…',
            capture_path: 'captures/shot-1-2.png',
            output_path: DEMO_OUTPUT,
          }),
        ],
      }),
      shot('shot-1-3', 3, 'The console answers', {
        shot_size: 'xcu',
        description: 'One line of text resolves on a dead screen.',
        action: 'Cursor blinks twice, then a word appears.',
        location_id: 'asset-station',
        duration_seconds: 3,
        status: 'review',
        current_version: null,
        visual_prompt:
          'Extreme close-up of amber text resolving on a scratched CRT, scan lines, dust, shallow depth of field',
        versions: [
          version(1, {
            status: 'failed',
            kind: 'preview',
            error: 'Out of memory at 1080p. Try the Fast Preview profile or a lower resolution.',
            output_path: '',
            generation_seconds: null,
            peak_vram_gb: null,
          }),
        ],
      }),
    ],
  })

  const scene2 = scene('scene-2', 2, 'The ridge, dawn', {
    description: 'Mara climbs out and finds the antenna already turning.',
    location_id: 'asset-ridge',
    character_ids: ['asset-mara'],
    mood: 'awe, unease',
    lighting: 'flat blue pre-dawn',
    time_of_day: 'dawn',
    inter_shot_gap_seconds: 0.5,
    shots: [
      shot('shot-2-1', 1, 'Climbing out', {
        shot_size: 'full',
        camera_angle: 'back',
        description: 'She hauls herself through the roof hatch into blue light.',
        location_id: 'asset-ridge',
        characters: [
          { asset_id: 'asset-mara', pose_name: 'climb', emotion: 'strained', position_hint: 'lower third' },
        ],
        camera_move: 'tilt_up',
        duration_seconds: 5,
        status: 'composed',
        capture_path: 'captures/shot-2-1.png',
        composition: composition('full', 'back', 'lowerThird', 'tilt_up', 5),
        visual_prompt:
          'Full shot from behind of a climber pulling through a roof hatch into flat blue dawn, snow, wind, anamorphic 35mm',
      }),
      shot('shot-2-2', 2, 'The antenna', {
        shot_size: 'wide',
        camera_angle: 'threeQuarterRight',
        description: 'A lattice antenna turning against an empty valley.',
        action: 'It rotates a few degrees and stops.',
        location_id: 'asset-ridge',
        camera_move: 'orbit',
        duration_seconds: 7,
        status: 'draft',
        visual_prompt:
          'Wide shot of a lattice radio antenna turning on a snow ridge at dawn, empty valley below, cold blue light',
      }),
      shot('shot-2-3', 3, 'Mara reacts', {
        shot_size: 'closeup',
        description: 'She works out what it means.',
        dialogue: 'Somebody is still pointing it.',
        emotion: 'unsettled',
        // Deliberately the ridge scene with the station's night lighting on the
        // character: the continuity panel has something real to report.
        location_id: 'asset-station',
        characters: [
          { asset_id: 'asset-mara', pose_name: 'stand', emotion: 'unsettled', position_hint: 'right third' },
        ],
        duration_seconds: 4,
        status: 'draft',
        visual_prompt: 'Close-up of a field engineer at dawn realising something, breath visible, cold blue light',
      }),
    ],
  })

  return {
    schema_version: 4,
    id,
    name: name || 'The Relay (demo)',
    script: { content: SCRIPT, updated_at: stamp() },
    settings: {
      default_model: 'fast',
      default_resolution: '1280x720',
      style_prompt: 'anamorphic 35mm, halation on practicals, muted teal and amber, fine grain',
      default_negative_prompt: 'text, watermark, logo, distorted hands',
      inter_shot_gap_seconds: 0.25,
      strict_continuity: false,
      default_quality_preset: 'balanced',
      preview_resolution: '960x540',
      preview_max_seconds: 4,
      media_provider: '',
      video_model: '',
      image_model: '',
    },
    assets,
    scenes: [scene1, scene2],
    pose_library: [
      { id: 'pose-crouch', name: 'Crouch', category: 'default', joints: {} },
      { id: 'pose-climb', name: 'Climb', category: 'default', joints: {} },
      { id: 'pose-stand', name: 'Stand', category: 'default', joints: {} },
    ],
    created_at: T0,
    updated_at: stamp(),
  }
}

export function seedSettings(): AppSettings {
  return {
    useTorchCompile: false,
    loadOnStartup: true,
    hasLtxApiKey: false,
    userPrefersLtxApiVideoGenerations: false,
    hasFalApiKey: false,
    hasGeminiApiKey: false,
    hasOpenrouterApiKey: false,
    openrouterKeySource: 'none',
    directorProvider: 'auto',
    openrouterModels: {
      defaultModel: 'openai/gpt-4o-mini',
      script: '',
      storyboard: '',
      director: '',
      continuity: '',
      prompt_refinement: '',
    },
    openaiCompatibleBaseUrl: '',
    openaiCompatibleModel: '',
    hasOpenaiCompatibleApiKey: false,
    hasAnthropicApiKey: false,
    anthropicModel: '',
    hasXaiApiKey: false,
    xaiModel: '',
    geminiModel: '',
    mediaProvider: 'local',
    hasWavespeedApiKey: false,
    hasReplicateApiKey: false,
    defaultVideoModel: '',
    defaultImageModel: '',
    recentModelIds: [],
    useLocalTextEncoder: true,
    fastModel: { useUpscaler: true },
    proModel: { steps: 20, useUpscaler: true },
    promptCacheSize: 1,
    promptEnhancerEnabledT2V: false,
    promptEnhancerEnabledI2V: false,
    seedLocked: false,
    lockedSeed: 42,
  }
}
