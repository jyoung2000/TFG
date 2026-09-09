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
      applyPatch(asset, req.body, ['id', 'created_at'])
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
      applyPatch(shot, req.body, ['id', 'versions', 'composition', 'clear_location', 'clear_gap'])
      if ('composition' in req.body) {
        syncComposition(shot, (req.body.composition as CompositionScene | null) ?? null)
      }
      if (req.body.clear_location === true) shot.location_id = null
      if (req.body.clear_gap === true) shot.gap_before_seconds = null
      shot.updated_at = now()
      touched(p)
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
