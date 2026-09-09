/**
 * Build Film with AI, storyboard generation, promoting a quick generation into
 * a film, and `.ltxfilm` packages.
 *
 * The plan produced here is the deterministic offline one — the same thing the
 * real backend falls back to with no provider — so the Build Film dialog can be
 * worked on end to end.
 */

import type {
  FilmBuildPlan,
  FilmBuildScene,
  FilmProject,
  FilmScene,
  FilmShot,
  PackageSummary,
  ShotSize,
} from '../../../frontend/types/film'
import { MockHttpError, type Router } from '../http'
import { seedProject } from '../seed'
import type { Store } from '../state'

const SIZES: ShotSize[] = ['wide', 'medium', 'mcu', 'closeup']

function titleCase(value: string): string {
  return value.replace(/\b[a-z]/g, ch => ch.toUpperCase())
}

/** Split an idea into beats the way the offline planner does: on sentences. */
function beats(idea: string, count: number): string[] {
  const sentences = idea
    .split(/[.!?\n]+/)
    .map(s => s.trim())
    .filter(Boolean)
  if (sentences.length >= count) return sentences.slice(0, count)
  const out = [...sentences]
  const openers = ['Setup', 'Complication', 'Turn', 'Consequence', 'Resolution']
  while (out.length < count) out.push(`${openers[out.length % openers.length]} of ${idea.slice(0, 60) || 'the story'}`)
  return out
}

function buildPlan(idea: string, targetScenes: number, shotsPerScene: number, style: string): FilmBuildPlan {
  const trimmed = idea.trim() || 'An unnamed idea'
  const scenes: FilmBuildScene[] = beats(trimmed, targetScenes).map((beat, index) => ({
    title: `${index + 1}. ${titleCase(beat.slice(0, 48))}`,
    description: beat,
    location: index % 2 === 0 ? 'Interior' : 'Exterior',
    time_of_day: index % 2 === 0 ? 'night' : 'day',
    mood: index === 0 ? 'curious' : index === targetScenes - 1 ? 'resolved' : 'tense',
    lighting: index % 2 === 0 ? 'practical lamps, deep shadow' : 'flat natural light',
    characters: ['Lead'],
    shots: Array.from({ length: shotsPerScene }, (_, shotIndex) => ({
      title: `Shot ${index + 1}.${shotIndex + 1}`,
      description: beat,
      action: shotIndex === 0 ? 'Establish the space.' : 'Play the beat on the lead.',
      dialogue: '',
      shot_size: SIZES[shotIndex % SIZES.length],
      camera_angle: shotIndex % 3 === 2 ? ('threeQuarterLeft' as const) : ('front' as const),
      camera_elevation: 'eye' as const,
      composition: shotIndex % 2 === 0 ? ('center' as const) : ('rightThird' as const),
      camera_move: shotIndex === 0 ? ('push_in' as const) : ('static' as const),
      duration_seconds: 4 + (shotIndex % 3),
      characters: shotIndex === 0 ? [] : ['Lead'],
      location: index % 2 === 0 ? 'Interior' : 'Exterior',
    })),
  }))

  return {
    title: titleCase(trimmed.split(/[.!?\n]/)[0].slice(0, 60)) || 'Untitled',
    logline: trimmed.slice(0, 180),
    style: style || 'anamorphic 35mm, muted palette, practical light',
    script: scenes.map(scene => `${scene.location.toUpperCase()}. ${scene.title}\n\n${scene.description}\n`).join('\n'),
    characters: [
      { name: 'Lead', description: 'Carries the story.', appearance: 'Unspecified', wardrobe: 'Unspecified' },
    ],
    locations: [
      { name: 'Interior', description: 'The inside space.', environment: 'Enclosed', lighting: 'Practical', atmosphere: 'Close' },
      { name: 'Exterior', description: 'The outside space.', environment: 'Open', lighting: 'Natural', atmosphere: 'Exposed' },
    ],
    scenes,
  }
}

function applyPlan(project: FilmProject, plan: FilmBuildPlan, replaceExisting: boolean) {
  const template = seedProject('tmp')
  const assetTemplate = template.assets[0]
  const shotTemplate = template.scenes[0].shots[0]
  const now = Date.now()

  if (replaceExisting) {
    project.scenes = []
    project.assets = []
  }

  let charactersCreated = 0
  let locationsCreated = 0
  const assetIdByName = new Map(project.assets.map(a => [a.name.toLowerCase(), a.id]))

  const ensureAsset = (kind: 'character' | 'location', name: string, fields: Record<string, string>): string => {
    const existing = assetIdByName.get(name.toLowerCase())
    if (existing) return existing
    const id = `asset-${kind}-${Math.random().toString(36).slice(2, 8)}`
    project.assets.push({ ...assetTemplate, ...fields, id, kind, name, reference_images: [], created_at: now, updated_at: now })
    assetIdByName.set(name.toLowerCase(), id)
    if (kind === 'character') charactersCreated += 1
    else locationsCreated += 1
    return id
  }

  for (const character of plan.characters) {
    ensureAsset('character', character.name, {
      description: character.description,
      appearance: character.appearance,
      wardrobe: character.wardrobe,
    })
  }
  for (const location of plan.locations) {
    ensureAsset('location', location.name, {
      description: location.description,
      environment: location.environment,
      lighting: location.lighting,
      atmosphere: location.atmosphere,
    })
  }

  let shotsCreated = 0
  for (const [index, planScene] of plan.scenes.entries()) {
    const locationId = planScene.location ? ensureAsset('location', planScene.location, {}) : null
    const scene: FilmScene = {
      id: `scene-${Math.random().toString(36).slice(2, 8)}`,
      order: project.scenes.length + 1,
      title: planScene.title,
      description: planScene.description,
      location_id: locationId,
      character_ids: planScene.characters.map(name => ensureAsset('character', name, {})),
      prop_ids: [],
      mood: planScene.mood,
      lighting: planScene.lighting,
      time_of_day: planScene.time_of_day,
      continuity_notes: '',
      inter_shot_gap_seconds: null,
      shots: planScene.shots.map((planShot, shotIndex): FilmShot => {
        shotsCreated += 1
        return {
          ...shotTemplate,
          id: `shot-${Math.random().toString(36).slice(2, 8)}`,
          order: shotIndex + 1,
          title: planShot.title,
          description: planShot.description,
          action: planShot.action,
          dialogue: planShot.dialogue,
          duration_seconds: planShot.duration_seconds,
          framing: {
            ...shotTemplate.framing,
            shot_size: planShot.shot_size,
            camera_angle: planShot.camera_angle,
            camera_elevation: planShot.camera_elevation,
            composition: planShot.composition,
          },
          camera_move: planShot.camera_move,
          characters: planShot.characters.map(name => ({
            asset_id: ensureAsset('character', name, {}),
            pose_name: '',
            emotion: '',
            position_hint: '',
          })),
          location_id: locationId,
          prop_ids: [],
          composition: null,
          capture_path: '',
          versions: [],
          current_version: null,
          status: 'draft',
          visual_prompt: '',
          created_at: now + index,
          updated_at: now + index,
        }
      }),
    }
    project.scenes.push(scene)
  }

  if (plan.script.trim()) project.script = { content: plan.script, updated_at: now }
  if (plan.style.trim()) project.settings.style_prompt = plan.style
  if (plan.title.trim() && replaceExisting) project.name = plan.title
  project.updated_at = now

  return { scenes_created: plan.scenes.length, shots_created: shotsCreated, characters_created: charactersCreated, locations_created: locationsCreated }
}

function summarize(project: FilmProject, path: string, includeOutputs: boolean): PackageSummary {
  const shots = project.scenes.reduce((total, scene) => total + scene.shots.length, 0)
  const media = project.scenes.reduce(
    (total, scene) => total + scene.shots.filter(shot => shot.capture_path).length,
    project.assets.reduce((total, asset) => total + asset.reference_images.length, 0),
  )
  return {
    project_id: project.id,
    project_name: project.name,
    schema_version: project.schema_version,
    scenes: project.scenes.length,
    shots,
    assets: project.assets.length,
    media_files: media,
    includes_outputs: includeOutputs,
    total_bytes: 4096 + shots * 1024,
    warnings: ['UI-only mode: this package summary is synthetic and no file was written.'],
    path,
  }
}

export function registerProjectOpsRoutes(router: Router, store: Store): void {
  router.post('/api/film/projects/:projectId/build', req => {
    const project = store.ensureProject(req.params.projectId)
    const plan = buildPlan(
      String(req.body.idea ?? ''),
      Number(req.body.target_scenes ?? 3) || 3,
      Number(req.body.target_shots_per_scene ?? 3) || 3,
      String(req.body.style ?? project.settings.style_prompt),
    )
    return { plan, used_llm: false, context: null }
  })

  router.post('/api/film/projects/:projectId/build/apply', req =>
    store.mutate(() => {
      const project = store.ensureProject(req.params.projectId)
      const plan = req.body.plan as FilmBuildPlan | undefined
      if (!plan || !Array.isArray(plan.scenes)) throw new MockHttpError(400, 'Missing plan')
      const counts = applyPlan(project, plan, req.body.replace_existing === true)
      return { status: 'ok', ...counts, project }
    }),
  )

  router.post('/api/film/projects/:projectId/storyboard/generate', req =>
    store.mutate(() => {
      const project = store.ensureProject(req.params.projectId)
      const script = project.script.content.trim()
      if (!script) throw new MockHttpError(400, 'The script is empty — write or paste a script first.')
      const shotsPerScene = Number(req.body.target_shots_per_scene ?? 3) || 3
      // Scene headings drive the split, exactly like the offline parser.
      const headings = script.split(/\n(?=(?:INT|EXT)[\s.])/i).filter(part => part.trim())
      const plan = buildPlan(
        headings.map(h => h.replace(/\s+/g, ' ').slice(0, 120)).join('. '),
        Math.max(1, headings.length),
        shotsPerScene,
        project.settings.style_prompt,
      )
      plan.script = script
      const counts = applyPlan(project, plan, req.body.replace_existing === true)
      return {
        status: 'ok',
        scenes_created: counts.scenes_created,
        shots_created: counts.shots_created,
        characters_created: counts.characters_created,
        used_llm: false,
      }
    }),
  )

  router.post('/api/film/projects/:projectId/import-generation', req =>
    store.mutate(() => {
      const project = store.ensureProject(req.params.projectId)
      const outputPath = String(req.body.output_path ?? '')
      if (!/\.(mp4|webm|mov|mkv)$/i.test(outputPath)) {
        throw new MockHttpError(400, `Generated video has an unsupported file type: ${outputPath.split('.').pop() ?? 'none'}`)
      }
      const template = seedProject('tmp').scenes[0].shots[0]
      const now = Date.now()
      const scene: FilmScene = {
        id: `scene-${Math.random().toString(36).slice(2, 8)}`,
        order: project.scenes.length + 1,
        title: 'Scene 1',
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
      }
      const shot: FilmShot = {
        ...template,
        id: `shot-${Math.random().toString(36).slice(2, 8)}`,
        order: 1,
        title: String(req.body.title ?? 'Shot 1'),
        description: '',
        action: '',
        dialogue: '',
        visual_prompt: String(req.body.prompt ?? ''),
        negative_prompt: String(req.body.negative_prompt ?? ''),
        prompt_locked: true,
        duration_seconds: Number(req.body.duration_seconds ?? 5) || 5,
        composition: null,
        capture_path: '',
        current_version: 1,
        status: 'review',
        created_at: now,
        updated_at: now,
        generation: {
          ...template.generation,
          model: String(req.body.model ?? ''),
          resolution: String(req.body.resolution ?? ''),
          fps: Number(req.body.fps ?? 24) || 24,
          seed: req.body.seed == null ? null : Number(req.body.seed),
          aspect_ratio: req.body.aspect_ratio === '9:16' ? '9:16' : '16:9',
        },
        versions: [
          {
            number: 1,
            kind: 'final',
            status: 'complete',
            prompt: String(req.body.prompt ?? ''),
            negative_prompt: String(req.body.negative_prompt ?? ''),
            model: String(req.body.model ?? ''),
            resolution: String(req.body.resolution ?? ''),
            fps: Number(req.body.fps ?? 24) || 24,
            duration_seconds: Number(req.body.duration_seconds ?? 5) || 5,
            seed: req.body.seed == null ? null : Number(req.body.seed),
            capture_path: '',
            output_path: outputPath,
            error: '',
            wardrobe_snapshot: {},
            shot_snapshot: {},
            generation_seconds: null,
            gpu_name: '',
            peak_vram_gb: null,
            execution_mode: 'wangp',
            created_at: now,
          },
        ],
      }
      scene.shots.push(shot)
      project.scenes.push(scene)
      if (typeof req.body.project_name === 'string' && req.body.project_name.trim()) {
        project.name = req.body.project_name.trim()
      }
      project.updated_at = now
      return { project, scene_id: scene.id, shot_id: shot.id, version_number: 1 }
    }),
  )

  router.post('/api/film/projects/:projectId/export', req => {
    const project = store.ensureProject(req.params.projectId)
    return summarize(project, String(req.body.destination_path ?? ''), req.body.include_outputs === true)
  })

  router.get('/api/film/packages/inspect', req => {
    const project = store.ensureProject('ui-mock-film')
    return summarize(project, req.query.get('package_path') ?? '', false)
  })

  router.post('/api/film/projects/:projectId/import', req => {
    const project = store.ensureProject(req.params.projectId)
    return { summary: summarize(project, String(req.body.package_path ?? ''), false), project }
  })
}
