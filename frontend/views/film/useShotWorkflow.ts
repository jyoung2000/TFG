/**
 * The shot's generation / review / hand-off actions, shared by the storyboard
 * drawer and the Shot Composer so both edit the same FilmShot the same way.
 *
 * "Send to Timeline" links the host asset back to the film shot (Asset.filmRef)
 * so the editor can offer "Edit / Regenerate Shot" and replace the clip when a
 * newer version is promoted.
 */

import { useCallback, useMemo, useState } from 'react'
import { useProjects } from '../../contexts/ProjectContext'
import { useFilm } from '../../contexts/FilmContext'
import { copyToAssetFolder } from '../../lib/asset-copy'
import { filmApi } from '../../lib/film-api'
import { logger } from '../../lib/logger'
import type { Asset, TimelineClip } from '../../types/project'
import { DEFAULT_COLOR_CORRECTION } from '../../types/project'
import type { ContinuityWarning, FilmScene, FilmShot, ShotVersion, VersionKind } from '../../types/film'

export interface ShotQueueInfo {
  /** True when this shot is the job the backend is rendering right now. */
  active: boolean
  /** 0-100 host progress for the active job, when known. */
  progress: number | null
  phase: string
  /** 1-based position in the pending queue, or null when not pending. */
  pendingPosition: number | null
}

export function useShotWorkflow(scene: FilmScene, shot: FilmShot) {
  const { film, refresh, queue } = useFilm()
  const { currentProjectId, addAsset, updateTimeline, getActiveTimeline } = useProjects()
  const projectId = film?.id ?? ''
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState('')

  const currentVersion: ShotVersion | undefined = useMemo(
    () => (shot.current_version != null ? shot.versions.find(v => v.number === shot.current_version) : undefined),
    [shot.versions, shot.current_version],
  )

  const queueInfo: ShotQueueInfo = useMemo(() => {
    const active = queue.active?.shot_id === shot.id
    const index = queue.pending.findIndex(job => job.shot_id === shot.id)
    return {
      active,
      progress: active ? queue.progress : null,
      phase: active ? queue.phase : '',
      pendingPosition: index >= 0 ? index + 1 : null,
    }
  }, [queue, shot.id])

  const generate = useCallback(
    async (kind: VersionKind): Promise<ContinuityWarning[] | null> => {
      if (!projectId) return null
      setBusy(kind)
      try {
        const result = await filmApi.generateShot(projectId, scene.id, shot.id, kind)
        setNote(kind === 'preview' ? 'Preview queued' : 'Final queued')
        await refresh()
        return result.warnings
      } catch (e) {
        setNote(`Generate failed: ${e instanceof Error ? e.message : e}`)
        return null
      } finally {
        setBusy(null)
      }
    },
    [projectId, scene.id, shot.id, refresh],
  )

  const cancelJob = useCallback(async () => {
    setBusy('cancel')
    try {
      await filmApi.cancelJob(shot.id)
      await refresh()
      setNote('Cancelled')
    } catch (e) {
      setNote(`Cancel failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [shot.id, refresh])

  const promote = useCallback(
    async (number: number) => {
      if (!projectId) return
      setBusy('promote')
      try {
        await filmApi.promoteVersion(projectId, scene.id, shot.id, number)
        await refresh()
        setNote(`v${number} is now current`)
      } catch (e) {
        setNote(`Promote failed: ${e instanceof Error ? e.message : e}`)
      } finally {
        setBusy(null)
      }
    },
    [projectId, scene.id, shot.id, refresh],
  )

  const setStatus = useCallback(
    async (status: FilmShot['status']) => {
      if (!projectId) return
      setBusy('status')
      try {
        await filmApi.updateShot(projectId, scene.id, shot.id, { status })
        await refresh()
      } catch (e) {
        setNote(`Status change failed: ${e instanceof Error ? e.message : e}`)
      } finally {
        setBusy(null)
      }
    },
    [projectId, scene.id, shot.id, refresh],
  )

  /** The timeline clip (if any) already linked to this film shot. */
  const linkedClip = useMemo((): TimelineClip | null => {
    if (!currentProjectId) return null
    const timeline = getActiveTimeline(currentProjectId)
    return timeline?.clips.find(clip => clip.asset?.filmRef?.shotId === shot.id) ?? null
  }, [currentProjectId, getActiveTimeline, shot.id])

  /**
   * Copy the version's output into the host project's asset folder, register
   * it as an Asset (with filmRef) and append it to the active timeline — or,
   * with `replace`, swap it into the clip already linked to this shot.
   */
  const sendToTimeline = useCallback(
    async (version: ShotVersion | undefined = currentVersion, options: { replace?: boolean } = {}) => {
      if (!currentProjectId || !version || version.status !== 'complete') return false
      setBusy('timeline')
      try {
        const copied = await copyToAssetFolder(version.output_path, currentProjectId)
        const path = copied?.path ?? version.output_path
        const url =
          copied?.url ?? (path.startsWith('/') ? `file://${path}` : `file:///${path.replace(/\\/g, '/')}`)
        const asset: Asset = addAsset(currentProjectId, {
          type: 'video',
          path,
          url,
          prompt: version.prompt,
          resolution: version.resolution,
          duration: version.duration_seconds,
          generationParams: {
            mode: version.capture_path ? 'image-to-video' : 'text-to-video',
            prompt: version.prompt,
            model: version.model,
            duration: version.duration_seconds,
            resolution: version.resolution,
            fps: version.fps,
            audio: false,
            cameraMotion: 'none',
          },
          takes: [{ url, path, createdAt: Date.now() }],
          activeTakeIndex: 0,
          filmRef: { projectId, sceneId: scene.id, shotId: shot.id, versionNumber: version.number },
        })

        const timeline = getActiveTimeline(currentProjectId)
        if (timeline) {
          const existing = options.replace
            ? timeline.clips.find(clip => clip.asset?.filmRef?.shotId === shot.id)
            : undefined
          if (existing) {
            const clips = timeline.clips.map(clip =>
              clip.id === existing.id
                ? { ...clip, assetId: asset.id, asset, duration: version.duration_seconds, trimStart: 0, trimEnd: 0 }
                : clip,
            )
            updateTimeline(currentProjectId, timeline.id, { clips })
            setNote(`Replaced the timeline clip with v${version.number}`)
            return true
          }
          const videoTrackIndex = Math.max(
            0,
            timeline.tracks.findIndex(t => t.kind === 'video' || t.kind === undefined),
          )
          const clipsOnTrack = timeline.clips.filter(c => c.trackIndex === videoTrackIndex)
          const endTime = clipsOnTrack.reduce((max, clip) => Math.max(max, clip.startTime + clip.duration), 0)
          const gap = shot.gap_before_seconds ?? scene.inter_shot_gap_seconds ?? film?.settings.inter_shot_gap_seconds ?? 0
          const newClip: TimelineClip = {
            id: `clip-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
            assetId: asset.id,
            type: 'video',
            startTime: endTime > 0 ? endTime + gap : 0,
            duration: version.duration_seconds,
            trimStart: 0,
            trimEnd: 0,
            speed: 1,
            reversed: false,
            muted: false,
            volume: 1,
            trackIndex: videoTrackIndex,
            asset,
            flipH: false,
            flipV: false,
            transitionIn: { type: 'none', duration: 0.5 },
            transitionOut: { type: 'none', duration: 0.5 },
            colorCorrection: { ...DEFAULT_COLOR_CORRECTION },
            opacity: 100,
          }
          updateTimeline(currentProjectId, timeline.id, { clips: [...timeline.clips, newClip] })
        }
        setNote('Sent to timeline — open the Video Editor tab')
        return true
      } catch (e) {
        logger.error(`Send to timeline failed: ${e}`)
        setNote(`Send to timeline failed: ${e instanceof Error ? e.message : e}`)
        return false
      } finally {
        setBusy(null)
      }
    },
    [
      currentProjectId,
      currentVersion,
      addAsset,
      getActiveTimeline,
      updateTimeline,
      projectId,
      scene.id,
      scene.inter_shot_gap_seconds,
      shot.id,
      shot.gap_before_seconds,
      film?.settings.inter_shot_gap_seconds,
    ],
  )

  return {
    projectId,
    busy,
    note,
    setNote,
    currentVersion,
    queueInfo,
    linkedClip,
    generate,
    cancelJob,
    promote,
    setStatus,
    sendToTimeline,
  }
}
