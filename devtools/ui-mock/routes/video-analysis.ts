/**
 * Video analysis, simulated.
 *
 * Mirrors the real pipeline's shape and its honesty: detection is deterministic
 * and needs no provider, measured fields are filled while inferred ones stay
 * empty with zero confidence until a "model" runs, and a shot with no cuts is
 * reported as an even split rather than invented cuts.
 */

import type { FilmProject } from '../../../frontend/types/film'
import { EMPTY_MOTION, type AnalyzedShot, type VideoAnalysis } from '../../../frontend/types/video-analysis'
import { emptySpec } from '../../../frontend/lib/shotspec/schema'
import { EMPTY_BRIEF } from '../../../frontend/types/prompts'
import { MockHttpError, type Router } from '../http'
import { compilePrompt } from './prompts'
import { placeholderFrame } from '../media'
import { seedProject } from '../seed'
import type { MockState, Store } from '../state'

/** What this user could render with: their configured models plus the local host. */
function compileTargets(state: MockState): string[] {
  return [state.settings.defaultVideoModel ?? '', 'ltx-2']
    .map(model => model.trim())
    .filter((model, index, all) => model && all.indexOf(model) === index)
}

const DEMO_CUTS = [2.0, 4.0, 6.5, 9.0, 11.0]
const DURATION = 13.5

function emptyShot(index: number, start: number, end: number): AnalyzedShot {
  return {
    id: `vs-${index}-${Math.random().toString(36).slice(2, 8)}`,
    index,
    start: Math.round(start * 1000) / 1000,
    end: Math.round(end * 1000) / 1000,
    duration: Math.round((end - start) * 1000) / 1000,
    detection_confidence: 1,
    detection_method: 'cut',
    boundary_edited: false,
    frames: [{ path: `frames/shot-${index}.jpg`, timestamp: (start + end) / 2, role: 'representative' }],
    visual: {
      description: '', subjects: [], character_estimates: [], objects: [], location: '', environment: '',
      foreground: '', midground: '', background: '', composition: '', framing: '', shot_size: '', angle: '',
      camera_height: '', perspective: '', lens_estimate: '', depth_of_field: '', focus: '', lighting: '',
      palette: [], contrast: '', visual_style: '', production_design: '', wardrobe: '', props: [], confidence: 0,
    },
    cinematography: {
      camera_position: '', camera_movement: '', movement_types: [], is_static: true, screen_direction: '',
      eyeline: '', ots_relationship: '', blocking: '', composition_rules: [], confidence: 0,
    },
    narrative: {
      what_happens: '', who_acts: [], narrative_purpose: '', emotional_purpose: '', story_beat: '',
      setup_or_payoff: '', continuity_implications: [], pacing: '', transition_role: '', confidence: 0,
    },
    editorial: {
      transition_in: '', transition_out: '', cut_type: '', rhythm: '', approximate_beat: '',
      montage_role: '', broll_role: '', confidence: 0,
    },
    audio: { analyzed: false, dialogue: '', transcription: '', voiceover: '', ambience: '', music: '', sfx: [], silence: false, emphasis: '', rhythm: '', confidence: 0 },
    text: { analyzed: false, visible_text: [], subtitles: [], signs: [], ui_text: [], typography: '', confidence: 0 },
    prompts: { storyboard: '', video: '', cinematography: '', environment: '', character: '', motion: '', negative: '', model_specific: {}, edited: false },
    prompt_lens: { core_prompt: '', deep_description: '', subject: '', environment: '', camera: '', lighting: '', style: '', mood: '', confidence: 0 },
    motion: { ...EMPTY_MOTION },
    spec: emptySpec('video_shot'),
    analysis_provider: '',
    analysis_model: '',
    provenance: 'measured',
    evidence_note: '',
    analyzed_at: 0,
  }
}

const MOTION_WORDS = ['static camera', 'pan left', 'push in']

/** Deterministic "measured" flow per shot index, so the strip shows variety. */
function mockMotion(index: number) {
  const kind = index % 3
  return {
    ...EMPTY_MOTION,
    analyzed: true,
    model: 'ui-mock-flow',
    pan: kind === 1 ? 0.008 : 0,
    zoom: kind === 2 ? 0.006 : 0,
    magnitude: kind === 0 ? 0.001 : 0.012,
    subject_motion: 0.003,
    pacing: kind === 0 ? 'still' : 'slow',
    frames_sampled: 12,
    confidence: 0.8,
  }
}

function newAnalysis(path: string, title: string): VideoAnalysis {
  const name = path.split(/[\\/]/).pop() ?? 'video.mp4'
  return {
    schema_version: 1,
    id: `va-${Date.now().toString(36)}`,
    title: title || name.replace(/\.[a-z0-9]+$/i, ''),
    source: {
      path, file_name: name, size_bytes: 24_500_000, duration_seconds: DURATION, fps: 24,
      width: 1920, height: 1080, aspect_ratio: '16:9', codec: 'h264', bit_rate: 2_500_000,
      frame_count: Math.round(DURATION * 24), has_audio: true, audio_codec: 'aac', audio_channels: 2,
      audio_sample_rate: 48000, rotation: 0, pixel_format: 'yuv420p',
    },
    shots: [],
    depth: 'standard', sensitivity: 0.5, min_shot_seconds: 0.6, max_shots: 400,
    detect_fades: true, analyze_audio: false, analyze_text: false, provider: '', model: '',
    stage: 'idle', progress: 0, message: 'Ready to detect shots', error: '',
    reconstructed_project_id: '', synopsis: '', visual_style: '', characters: [], locations: [],
    created_at: Date.now(), updated_at: Date.now(),
  }
}

function find(state: MockState, id: string): VideoAnalysis {
  const analysis = state.analyses[id]
  if (!analysis) throw new MockHttpError(404, `No analysis named ${id}`)
  return analysis
}

function renumber(shots: AnalyzedShot[]): AnalyzedShot[] {
  return shots.map((shot, index) => ({ ...shot, index }))
}

export function registerVideoAnalysisRoutes(router: Router, store: Store): void {
  router.post('/api/video-analysis/import', req =>
    store.mutate(state => {
      const path = String(req.body.path ?? '')
      if (!/\.(mp4|mov|mkv|webm|m4v|avi)$/i.test(path)) {
        throw new MockHttpError(400, `That is not a video this app can read: ${path}`)
      }
      const analysis = newAnalysis(path, String(req.body.title ?? ''))
      analysis.depth = (req.body.depth as VideoAnalysis['depth']) ?? 'standard'
      analysis.sensitivity = Number(req.body.sensitivity ?? 0.5)
      analysis.min_shot_seconds = Number(req.body.min_shot_seconds ?? 0.6)
      analysis.analyze_audio = req.body.analyze_audio === true
      analysis.analyze_text = req.body.analyze_text === true
      state.analyses[analysis.id] = analysis
      return analysis
    }),
  )

  router.get('/api/video-analysis', () => ({
    analyses: Object.values(store.data.analyses).sort((a, b) => b.created_at - a.created_at),
  }))

  router.get('/api/video-analysis/:id', req => find(store.data, req.params.id))

  router.delete('/api/video-analysis/:id', req =>
    store.mutate(state => {
      delete state.analyses[req.params.id]
      return { status: 'ok' }
    }),
  )

  router.post('/api/video-analysis/:id/detect', req =>
    store.mutate(state => {
      const analysis = find(state, req.params.id)
      const pinned = analysis.shots.filter(shot => shot.boundary_edited).length
      const edges = [0, ...DEMO_CUTS, DURATION]
      analysis.shots = renumber(edges.slice(0, -1).map((start, i) => emptyShot(i, start, edges[i + 1])))
      analysis.stage = 'idle'
      analysis.progress = 1
      analysis.message =
        `${analysis.shots.length} shots detected` +
        (pinned ? ` — ${pinned} edited boundar${pinned === 1 ? 'y was' : 'ies were'} replaced` : '')
      return analysis
    }),
  )

  router.post('/api/video-analysis/:id/analyze', req =>
    store.mutate(state => {
      const analysis = find(state, req.params.id)
      if (analysis.shots.length === 0) throw new MockHttpError(400, 'Detect shots before analysing them.')
      const offline = req.body.offline_only === true
      analysis.shots = analysis.shots.map(shot => {
        const duration = shot.duration
        const editorial = {
          ...shot.editorial,
          transition_in: 'cut',
          cut_type: shot.detection_method,
          rhythm: duration < 1.5 ? 'fast' : duration < 5 ? 'measured' : 'slow',
          approximate_beat: `${duration.toFixed(1)}s`,
          confidence: 0.9,
        }
        const motion = mockMotion(shot.index)
        const spec = { ...emptySpec('video_shot'), motion: { dominant: { pan: motion.pan, tilt: motion.tilt, zoom: motion.zoom, roll: motion.roll }, magnitude: motion.magnitude, subject_motion: motion.subject_motion, pacing: motion.pacing }, provenance: { motion: 'flow', measured: 'measured' }, confidence: { motion: 0.8 } }
        const cinematography = { ...shot.cinematography, camera_movement: MOTION_WORDS[shot.index % MOTION_WORDS.length], is_static: shot.index % 3 === 0, confidence: 0.8 }
        if (offline) return { ...shot, editorial, motion, spec, cinematography, analysis_provider: 'deterministic', provenance: 'measured' as const }
        return {
          ...shot,
          editorial,
          motion,
          spec,
          visual: {
            ...shot.visual,
            description: `Shot ${shot.index + 1} of the imported clip`,
            shot_size: ['wide', 'medium', 'closeup'][shot.index % 3],
            angle: 'front',
            lighting: 'available light',
            confidence: 0.55,
          },
          cinematography,
          prompts: shot.prompts.edited
            ? shot.prompts
            : {
                ...shot.prompts,
                storyboard: `${['wide', 'medium', 'closeup'][shot.index % 3]} shot`,
                video: `Shot ${shot.index + 1} of the imported clip, static camera, available light`,
                negative: 'text, watermark, logo, distorted hands, extra limbs',
                // Same rule as the app: compile for what this user could
                // actually render with, not for the whole catalog.
                model_specific: Object.fromEntries(
                  compileTargets(state).map(model => [
                    model,
                    compilePrompt(
                      {
                        ...EMPTY_BRIEF,
                        action: `Shot ${shot.index + 1} of the imported clip`,
                        shot_size: `${['wide', 'medium', 'closeup'][shot.index % 3]} shot`,
                        camera: 'front',
                        movement: 'static camera',
                        lighting: 'available light',
                        timeline: `${shot.duration.toFixed(1)} seconds`,
                        negative: ['text', 'watermark', 'logo'],
                      },
                      model,
                    ).prompt,
                  ]),
                ),
              },
          analysis_provider: 'ui-mock',
          analysis_model: 'mock-vision',
          provenance: 'inferred' as const,
          evidence_note: 'UI-only mode: this reading comes from the mock backend, not from a model.',
          analyzed_at: Date.now(),
        }
      })
      analysis.stage = 'complete'
      analysis.progress = 1
      analysis.message = offline
        ? `Described ${analysis.shots.length} shots without a model — connect one for a richer read`
        : `Analysed ${analysis.shots.length} shots`
      return analysis
    }),
  )

  router.post('/api/video-analysis/:id/cancel', req =>
    store.mutate(state => {
      const analysis = find(state, req.params.id)
      analysis.stage = 'cancelled'
      analysis.message = 'Cancelled'
      return analysis
    }),
  )

  router.post('/api/video-analysis/:id/shots/:shotId/split', req =>
    store.mutate(state => {
      const analysis = find(state, req.params.id)
      const index = analysis.shots.findIndex(shot => shot.id === req.params.shotId)
      if (index < 0) throw new MockHttpError(404, 'No such shot')
      const target = analysis.shots[index]
      const at = Number(req.body.at ?? 0)
      if (!(target.start < at && at < target.end)) throw new MockHttpError(400, 'That split point is outside the shot')
      const left = { ...emptyShot(index, target.start, at), boundary_edited: true }
      const right = { ...emptyShot(index + 1, at, target.end), boundary_edited: true }
      analysis.shots = renumber([...analysis.shots.slice(0, index), left, right, ...analysis.shots.slice(index + 1)])
      return analysis
    }),
  )

  router.post('/api/video-analysis/:id/shots/:shotId/merge', req =>
    store.mutate(state => {
      const analysis = find(state, req.params.id)
      const index = analysis.shots.findIndex(shot => shot.id === req.params.shotId)
      if (index < 0 || index + 1 >= analysis.shots.length) throw new MockHttpError(400, 'Nothing after this shot to merge with')
      const merged = { ...analysis.shots[index], end: analysis.shots[index + 1].end, boundary_edited: true }
      merged.duration = Math.round((merged.end - merged.start) * 1000) / 1000
      analysis.shots = renumber([...analysis.shots.slice(0, index), merged, ...analysis.shots.slice(index + 2)])
      return analysis
    }),
  )

  router.put('/api/video-analysis/:id/shots/:shotId/boundary', req =>
    store.mutate(state => {
      const analysis = find(state, req.params.id)
      const index = analysis.shots.findIndex(shot => shot.id === req.params.shotId)
      if (index < 0) throw new MockHttpError(404, 'No such shot')
      const start = req.body.start == null ? null : Number(req.body.start)
      const end = req.body.end == null ? null : Number(req.body.end)
      if (start != null && index > 0) {
        analysis.shots[index].start = start
        analysis.shots[index - 1].end = start
      }
      if (end != null && index < analysis.shots.length - 1) {
        analysis.shots[index].end = end
        analysis.shots[index + 1].start = end
      }
      for (const shot of analysis.shots) {
        shot.duration = Math.round((shot.end - shot.start) * 1000) / 1000
      }
      analysis.shots[index].boundary_edited = true
      return analysis
    }),
  )

  router.put('/api/video-analysis/:id/shots/:shotId/prompts', req =>
    store.mutate(state => {
      const analysis = find(state, req.params.id)
      const shot = analysis.shots.find(item => item.id === req.params.shotId)
      if (!shot) throw new MockHttpError(404, 'No such shot')
      let changed = false
      for (const field of ['storyboard', 'video', 'cinematography', 'environment', 'character', 'motion', 'negative'] as const) {
        const value = req.body[field]
        if (typeof value === 'string') {
          shot.prompts[field] = value
          changed = true
        }
      }
      if (changed) {
        shot.prompts.edited = true
        shot.provenance = 'user'
      }
      return analysis
    }),
  )

  router.post('/api/video-analysis/:id/reconstruct', req =>
    store.mutate(state => {
      const analysis = find(state, req.params.id)
      if (analysis.shots.length === 0) throw new MockHttpError(400, 'Detect shots before building a project.')
      const projectId = String(req.body.project_id ?? '') || `film-${Date.now().toString(36)}`
      const project = store.ensureProject(projectId, String(req.body.name ?? '') || analysis.title)
      project.name = String(req.body.name ?? '') || analysis.title
      project.scenes = [
        {
          id: `scene-${Date.now().toString(36)}`,
          order: 1,
          title: 'Reconstructed sequence',
          description: analysis.synopsis,
          location_id: null,
          character_ids: [],
          prop_ids: [],
          mood: '',
          lighting: '',
          time_of_day: '',
          continuity_notes: '',
          inter_shot_gap_seconds: null,
          shots: analysis.shots.map((shot, index) => ({
            ...seedProject('tmp').scenes[0].shots[0],
            id: `shot-${index}-${Math.random().toString(36).slice(2, 8)}`,
            order: index + 1,
            title: shot.visual.description || `Shot ${index + 1}`,
            description: shot.visual.description,
            duration_seconds: Math.max(0.5, shot.duration),
            visual_prompt: shot.prompts.video,
            negative_prompt: shot.prompts.negative,
            prompt_locked: Boolean(shot.prompts.video),
            source_ref: {
              kind: 'video_analysis' as const,
              analysis_id: analysis.id,
              analysis_shot_id: shot.id,
              source_path: analysis.source.path,
              start: shot.start,
              end: shot.end,
            },
          })),
        },
      ]
      analysis.reconstructed_project_id = project.id
      return project as FilmProject
    }),
  )

  // Evidence frames: labelled placeholders, same as the rest of the mock media.
  router.get('/api/video-analysis/:id/frame', req => {
    const path = req.query.get('path') ?? ''
    const analysis = store.data.analyses[req.params.id]
    const label = path.replace(/^frames\//, '').replace(/\.jpg$/, '')
    return placeholderFrame(label, analysis?.title ?? '', path)
  })
}
