/** Projects, scenes, shots, assets and poses. */

import type {
  CompositionScene,
  FilmAsset,
  FilmProject,
  FilmScene,
  FilmShot,
  FilmPose,
} from '../../../frontend/types/film'
import { MockHttpError, RawResponse, type Router } from '../http'
import { recordMockEvent } from './knowledge'
import { isVideoPath, labelFromPath, placeholderFrame } from '../media'
import type { Store } from '../state'
import { seedProject } from '../seed'

const now = () => Date.now()

function findScene(project: FilmProject, sceneId: string): FilmScene {
  const scene = project.scenes.find(s => s.id === sceneId)
  if (!scene) throw new MockHttpError(404, `Scene not found: ${sceneId}`)
  return scene
}

function findShot(scene: FilmScene, shotId: string): FilmShot {
  const shot = scene.shots.find(s => s.id === shotId)
  if (!shot) throw new MockHttpError(404, `Shot not found: ${shotId}`)
  return shot
}

function renumber<T extends { order: number }>(items: T[]): void {
  items.forEach((item, index) => {
    item.order = index + 1
  })
}

function reorderBy<T extends { id: string; order: number }>(items: T[], orderedIds: string[]): T[] {
  const byId = new Map(items.map(item => [item.id, item]))
  const next: T[] = []
  for (const id of orderedIds) {
    const item = byId.get(id)
    if (item) {
      next.push(item)
      byId.delete(id)
    }
  }
  // Anything the client did not mention keeps its relative position at the end,
  // which is what the backend does rather than dropping it.
  next.push(...items.filter(item => byId.has(item.id)))
  renumber(next)
  return next
}

function newId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`
}

/**
 * Apply a client patch to a record, ignoring keys the client did not send.
 * Mirrors the backend's `exclude_unset` behaviour on its update models.
 */
function applyPatch<T extends object>(target: T, patch: Record<string, unknown>, skip: string[] = []): void {
  for (const [key, value] of Object.entries(patch)) {
    if (skip.includes(key) || value === undefined) continue
    if (key in target) (target as Record<string, unknown>)[key] = value
  }
}

/** The composer is authoritative for framing when it saves a composition. */
function syncComposition(shot: FilmShot, composition: CompositionScene | null): void {
  shot.composition = composition
  if (!composition) return
  shot.framing = { ...composition.framing }
  shot.camera_move = composition.camera_move
  if (composition.duration_seconds > 0) shot.duration_seconds = composition.duration_seconds
}

export function registerFilmRoutes(router: Router, store: Store, clipUrl: string): void {
  const clip = () => new RawResponse(302, { location: clipUrl }, null)
  const project = (id: string): FilmProject => store.ensureProject(id)

  const touched = (p: FilmProject): { project: FilmProject } => {
    p.updated_at = now()
    return { project: p }
  }

  // ---- Project ----

  router.get('/api/film/projects/:projectId', req => ({ project: project(req.params.projectId) }))

  router.put('/api/film/projects/:projectId', req =>
    store.mutate(state => {
      const incoming = req.body.project as FilmProject | undefined
      if (!incoming || typeof incoming !== 'object') {
        throw new MockHttpError(400, 'Missing project payload')
      }
      if (state.queue.active || state.queue.pending.length > 0) {
        throw new MockHttpError(409, 'Cannot replace the project while shots are queued or rendering')
      }
      state.projects[req.params.projectId] = { ...incoming, id: req.params.projectId }
      return touched(state.projects[req.params.projectId])
    }),
  )

  router.put('/api/film/projects/:projectId/script', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      p.script = { content: String(req.body.content ?? ''), updated_at: now() }
      return touched(p)
    }),
  )

  router.put('/api/film/projects/:projectId/settings', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const settings = req.body.settings
      if (settings && typeof settings === 'object') {
        p.settings = { ...p.settings, ...(settings as Partial<FilmProject['settings']>) }
      }
      return touched(p)
    }),
  )

  // ---- Assets ----

  router.post('/api/film/projects/:projectId/assets', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const asset = seedProject('tmp').assets[0]
      const created: FilmAsset = {
        ...asset,
        ...(req.body as Partial<FilmAsset>),
        id: newId('asset'),
        reference_images: [],
        created_at: now(),
        updated_at: now(),
      }
      p.assets.push(created)
      touched(p)
      return { asset: created }
    }),
  )

  router.put('/api/film/projects/:projectId/assets/:assetId', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const asset = p.assets.find(a => a.id === req.params.assetId)
      if (!asset) throw new MockHttpError(404, `Asset not found: ${req.params.assetId}`)
      applyPatch(asset, req.body, ['id', 'created_at', 'clear_seed_lock'])
      if (req.body.clear_seed_lock) asset.seed_lock = null
      asset.updated_at = now()
      touched(p)
      return { asset }
    }),
  )

  router.delete('/api/film/projects/:projectId/assets/:assetId', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      p.assets = p.assets.filter(a => a.id !== req.params.assetId)
      touched(p)
      return { status: 'ok' }
    }),
  )

  router.post('/api/film/projects/:projectId/assets/:assetId/references', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const asset = p.assets.find(a => a.id === req.params.assetId)
      if (!asset) throw new MockHttpError(404, `Asset not found: ${req.params.assetId}`)
      const hint = String(req.body.name_hint ?? 'reference')
      asset.reference_images.push(`references/${asset.id}-${hint}-${asset.reference_images.length + 1}.png`)
      asset.updated_at = now()
      touched(p)
      return { asset }
    }),
  )

  router.post('/api/film/projects/:projectId/assets/:assetId/reference-sheet', req =>
    store.mutate(state => {
      const p = project(req.params.projectId)
      const asset = p.assets.find(a => a.id === req.params.assetId)
      if (!asset) throw new MockHttpError(404, `Asset not found: ${req.params.assetId}`)
      const views = ((req.body.views as string[] | undefined) ?? ['front view', 'three-quarter view', 'profile view', 'back view']).slice(0, 6)
      const seed = typeof req.body.seed === 'number' ? req.body.seed : asset.seed_lock ?? 4242
      const lora = state.training.loras.find(l => l.id === asset.lora_id)
      const trigger = asset.lora_trigger || lora?.trigger || ''
      const prompts = views.map(view => [trigger, `${asset.name}, ${asset.appearance || asset.description}`, view, 'consistent character sheet, same person, same outfit'].filter(Boolean).join(', '))
      const paths = views.map(view => `references/${asset.id}-${view.replace(/ /g, '-')}-${asset.reference_images.length + 1}.png`)
      asset.reference_images.push(...paths)
      if (asset.seed_lock === null) asset.seed_lock = seed
      asset.updated_at = now()
      touched(p)
      return { asset, prompts, seed, reference_paths: paths }
    }),
  )

  router.post('/api/film/projects/:projectId/assets/:assetId/generate-reference', req =>
    store.mutate(state => {
      const p = project(req.params.projectId)
      const asset = p.assets.find(a => a.id === req.params.assetId)
      if (!asset) throw new MockHttpError(404, `Asset not found: ${req.params.assetId}`)
      const provider = (p.settings.media_provider || state.settings.mediaProvider || 'local').trim()
      if (provider !== 'local' && !state.keys[provider as 'fal' | 'wavespeed' | 'replicate']) {
        throw new MockHttpError(
          400,
          `${provider.toUpperCase()}_KEY_MISSING: add the ${provider} API key in Settings → API Keys, or switch this project back to local generation.`,
        )
      }
      const path = `references/${asset.id}-ai-${asset.reference_images.length + 1}.png`
      asset.reference_images.push(path)
      asset.updated_at = now()
      touched(p)
      return {
        asset,
        prompt: String(req.body.prompt ?? '') || `${asset.name}, ${asset.appearance || asset.description}`,
        provider,
        model: (p.settings.image_model || state.settings.defaultImageModel || 'local-image').trim(),
        reference_path: path,
      }
    }),
  )

  router.post('/api/film/projects/:projectId/assets/:assetId/style-guide', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const asset = p.assets.find(a => a.id === req.params.assetId)
      if (!asset) throw new MockHttpError(404, `Asset not found: ${req.params.assetId}`)
      if (!asset.reference_images.length) throw new MockHttpError(400, 'Asset has no reference image to analyze')
      asset.style_guide = {
        key_traits: ['distinct silhouette', 'consistent materials', 'recognizable detail'],
        color_palette: ['warm brass', 'charcoal', 'soft cream'],
        mood: 'cinematic, tactile and grounded',
        recommended_prompt: `${asset.name}: ${asset.appearance || asset.description || 'preserve the visible shape, materials and color palette'}`,
      }
      asset.updated_at = now()
      touched(p)
      return { asset }
    }),
  )

  // ---- Scenes ----

  router.post('/api/film/projects/:projectId/scenes', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const created: FilmScene = {
        id: newId('scene'),
        order: p.scenes.length + 1,
        title: 'New scene',
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
        ...(req.body as Partial<FilmScene>),
      }
      p.scenes.push(created)
      renumber(p.scenes)
      touched(p)
      return created
    }),
  )

  router.put('/api/film/projects/:projectId/scenes/:sceneId', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const scene = findScene(p, req.params.sceneId)
      applyPatch(scene, req.body, ['id', 'shots', 'clear_location', 'clear_gap'])
      if (req.body.clear_location === true) scene.location_id = null
      if (req.body.clear_gap === true) scene.inter_shot_gap_seconds = null
      touched(p)
      return scene
    }),
  )

  router.delete('/api/film/projects/:projectId/scenes/:sceneId', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      p.scenes = p.scenes.filter(s => s.id !== req.params.sceneId)
      renumber(p.scenes)
      touched(p)
      return { status: 'ok' }
    }),
  )

  router.post('/api/film/projects/:projectId/scenes/reorder', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      p.scenes = reorderBy(p.scenes, (req.body.ordered_ids as string[]) ?? [])
      return touched(p)
    }),
  )

  // ---- Shots ----

  router.post('/api/film/projects/:projectId/scenes/:sceneId/shots', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const scene = findScene(p, req.params.sceneId)
      const template = seedProject('tmp').scenes[0].shots[0]
      const created: FilmShot = {
        ...template,
        id: newId('shot'),
        order: scene.shots.length + 1,
        title: 'New shot',
        description: '',
        action: '',
        dialogue: '',
        visual_prompt: '',
        composition: null,
        capture_path: '',
        blockout_path: '',
        versions: [],
        current_version: null,
        status: 'draft',
        characters: [],
        prop_ids: [],
        created_at: now(),
        updated_at: now(),
        ...(req.body as Partial<FilmShot>),
      }
      scene.shots.push(created)
      renumber(scene.shots)
      touched(p)
      return created
    }),
  )

  router.put('/api/film/projects/:projectId/scenes/:sceneId/shots/:shotId', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const shot = findShot(findScene(p, req.params.sceneId), req.params.shotId)
      const previousStatus = shot.status
      applyPatch(shot, req.body, ['id', 'versions', 'composition', 'clear_location', 'clear_gap'])
      if ('composition' in req.body) {
        syncComposition(shot, (req.body.composition as CompositionScene | null) ?? null)
      }
      if (req.body.clear_location === true) shot.location_id = null
      if (req.body.clear_gap === true) shot.gap_before_seconds = null
      shot.updated_at = now()
      touched(p)
      // A change of verdict is a judgement about the model that made it.
      if (shot.status !== previousStatus && (shot.status === 'approved' || shot.status === 'rejected')) {
        const version = shot.versions.find(v => v.number === shot.current_version)
        recordMockEvent(store.data, {
          kind: shot.status === 'approved' ? 'version_approved' : 'version_rejected',
          model: version?.model ?? '',
          provider: version?.execution_mode ?? '',
          project_id: p.id,
          scene_id: req.params.sceneId,
          shot_id: shot.id,
          version_number: shot.current_version,
          prompt: version?.prompt ?? shot.visual_prompt,
        })
      }
      return shot
    }),
  )

  router.delete('/api/film/projects/:projectId/scenes/:sceneId/shots/:shotId', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const scene = findScene(p, req.params.sceneId)
      scene.shots = scene.shots.filter(s => s.id !== req.params.shotId)
      renumber(scene.shots)
      touched(p)
      return { status: 'ok' }
    }),
  )

  router.post('/api/film/projects/:projectId/scenes/:sceneId/shots/reorder', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const scene = findScene(p, req.params.sceneId)
      scene.shots = reorderBy(scene.shots, (req.body.ordered_ids as string[]) ?? [])
      touched(p)
      return scene
    }),
  )

  router.post('/api/film/projects/:projectId/scenes/:sceneId/shots/:shotId/duplicate', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const scene = findScene(p, req.params.sceneId)
      const source = findShot(scene, req.params.shotId)
      const copy: FilmShot = {
        ...structuredClone(source),
        id: newId('shot'),
        order: source.order + 1,
        title: `${source.title} (copy)`,
        versions: [],
        current_version: null,
        status: source.composition ? 'composed' : 'draft',
        created_at: now(),
        updated_at: now(),
      }
      scene.shots.splice(source.order, 0, copy)
      renumber(scene.shots)
      touched(p)
      return copy
    }),
  )

  router.post('/api/film/projects/:projectId/scenes/:sceneId/shots/:shotId/deliver', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const shot = findShot(findScene(p, req.params.sceneId), req.params.shotId)
      const clean = Array.isArray(req.body.clean) ? (req.body.clean as string[]) : []
      const depth = Array.isArray(req.body.depth) ? (req.body.depth as string[]) : []
      const normal = Array.isArray(req.body.normal) ? (req.body.normal as string[]) : []
      if (!clean.length && !depth.length && !normal.length) throw new MockHttpError(400, 'Nothing to deliver: render at least one pass.')
      const version = Math.max(0, ...shot.versions.map(v => v.number)) + 1
      const dir = `deliver/${shot.id}/v${version}`
      const files: string[] = []
      if (clean.length) files.push(`${dir}/reference.mp4`)
      if (depth.length) files.push(`${dir}/depth.mp4`)
      if (normal.length) files.push(`${dir}/normal.mp4`)
      files.push(`${dir}/metadata.json`)
      if (req.body.composition) syncComposition(shot, req.body.composition as CompositionScene)
      shot.generation.control_video = clean.length ? `${dir}/reference.mp4` : ''
      shot.generation.depth_video = depth.length ? `${dir}/depth.mp4` : ''
      shot.updated_at = now()
      touched(p)
      return { package_dir: dir, files, control_video: shot.generation.control_video, depth_video: shot.generation.depth_video, shot }
    }),
  )

  router.post('/api/film/projects/:projectId/scenes/:sceneId/shots/:shotId/capture', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const shot = findShot(findScene(p, req.params.sceneId), req.params.shotId)
      syncComposition(shot, (req.body.composition as CompositionScene | null) ?? shot.composition)
      shot.capture_path = `captures/${shot.id}.png`
      shot.status = shot.status === 'draft' || shot.status === 'composed' ? 'ready' : shot.status
      shot.updated_at = now()
      touched(p)
      return shot
    }),
  )

  router.post('/api/film/projects/:projectId/scenes/:sceneId/shots/:shotId/versions/:number/promote', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const shot = findShot(findScene(p, req.params.sceneId), req.params.shotId)
      const number = Number(req.params.number)
      const version = shot.versions.find(v => v.number === number)
      if (!version) throw new MockHttpError(404, `Version not found: ${number}`)
      if (version.status !== 'complete') {
        throw new MockHttpError(400, 'Only a completed version can be promoted')
      }
      shot.current_version = number
      shot.updated_at = now()
      touched(p)
      return { status: 'ok', current_version: number }
    }),
  )

  // Deleting a take: the same refusals as the app, because the point of them
  // is what the user is stopped from doing by accident.
  router.delete('/api/film/projects/:projectId/scenes/:sceneId/shots/:shotId/versions/:number', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const shot = findShot(findScene(p, req.params.sceneId), req.params.shotId)
      const number = Number(req.params.number)
      const force = req.query.get('force') === 'true'
      const version = shot.versions.find(v => v.number === number)
      if (!version) throw new MockHttpError(404, `Version not found: ${number}`)
      if (version.status === 'deleted') throw new MockHttpError(400, `Version ${number} is already deleted`)
      if (version.status === 'queued' || version.status === 'generating') {
        throw new MockHttpError(400, 'That take is still rendering — cancel it before deleting it')
      }
      if (shot.current_version === number) {
        if (shot.status === 'approved') {
          throw new MockHttpError(
            400,
            'That is the approved take. Approve a different one, or set the shot back to review, before deleting it.',
          )
        }
        if (!force) {
          throw new MockHttpError(
            409,
            `Version ${number} is the take this shot is currently on. Delete it with force=true, or promote another take first.`,
          )
        }
      }

      const removedPath = version.output_path
      version.status = 'deleted'
      version.deleted_at = now()
      version.deleted_media = removedPath ? 'removed' : 'missing'
      version.output_path = ''
      version.error = ''

      if (shot.current_version === number) {
        const survivor = [...shot.versions]
          .sort((a, b) => b.number - a.number)
          .find(v => v.status === 'complete')
        shot.current_version = survivor?.number ?? null
        if (!survivor && (shot.status === 'review' || shot.status === 'approved' || shot.status === 'rejected')) {
          shot.status = shot.capture_path ? 'ready' : 'draft'
        }
      }
      shot.updated_at = now()
      touched(p)

      recordMockEvent(store.data, {
        kind: 'version_deleted',
        model: version.model,
        provider: version.execution_mode,
        project_id: p.id,
        scene_id: req.params.sceneId,
        shot_id: shot.id,
        version_number: number,
        prompt: version.prompt,
      })

      return {
        status: 'deleted',
        number,
        media: version.deleted_media,
        removed_path: removedPath,
        current_version: shot.current_version,
        remaining_versions: shot.versions.filter(v => v.status === 'complete').length,
      }
    }),
  )

  // ---- Poses ----

  router.post('/api/film/projects/:projectId/poses', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      const pose: FilmPose = {
        id: newId('pose'),
        name: String(req.body.name ?? 'Pose'),
        category: String(req.body.category ?? 'custom'),
        joints: (req.body.joints as FilmPose['joints']) ?? {},
      }
      p.pose_library.push(pose)
      touched(p)
      return { pose }
    }),
  )

  router.delete('/api/film/projects/:projectId/poses/:poseId', req =>
    store.mutate(() => {
      const p = project(req.params.projectId)
      p.pose_library = p.pose_library.filter(pose => pose.id !== req.params.poseId)
      touched(p)
      return { status: 'ok' }
    }),
  )

  // ---- Media ----

  router.get('/api/film/projects/:projectId/media', req => {
    const path = req.query.get('path') ?? ''
    if (isVideoPath(path) && clipUrl) return clip()
    return placeholderFrame(labelFromPath(path), `${req.params.projectId} · ${path}`, path)
  })

  router.get('/api/film/output', req => {
    const path = req.query.get('path') ?? ''
    if (isVideoPath(path) && clipUrl) return clip()
    return placeholderFrame(labelFromPath(path), path, path)
  })
}
