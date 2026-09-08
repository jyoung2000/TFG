import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Aperture,
  Check,
  CheckCircle2,
  Film,
  Loader2,
  RefreshCw,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Wand2,
  X,
} from 'lucide-react'
import { useAppSettings } from '../../contexts/AppSettingsContext'
import { useProjects } from '../../contexts/ProjectContext'
import { useFilm } from '../../contexts/FilmContext'
import { copyToAssetFolder } from '../../lib/asset-copy'
import { filmApi, filmMediaUrl, filmOutputUrl } from '../../lib/film-api'
import { logger } from '../../lib/logger'
import { Button } from '../../components/ui/button'
import type { Asset, TimelineClip } from '../../types/project'
import { DEFAULT_COLOR_CORRECTION } from '../../types/project'
import type {
  ContinuityWarning,
  FilmScene,
  FilmShot,
  ShotVersion,
  VersionKind,
} from '../../types/film'
import { CAMERA_MOVES, SHOT_STATUS_META, framingLabel } from '../../types/film'

interface ShotDetailDrawerProps {
  scene: FilmScene
  shot: FilmShot
  onClose: () => void
  onCompose: () => void
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] text-zinc-500 uppercase tracking-wide">{label}</span>
      <div className="mt-0.5">{children}</div>
    </label>
  )
}

const inputClass =
  'w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600'

export function ShotDetailDrawer({ scene, shot, onClose, onCompose }: ShotDetailDrawerProps) {
  const { film, refresh, capabilities, isGenerating } = useFilm()
  const { currentProjectId, addAsset, updateTimeline, getActiveTimeline } = useProjects()
  const projectId = film?.id ?? ''

  const [draft, setDraft] = useState({
    title: shot.title,
    description: shot.description,
    action: shot.action,
    dialogue: shot.dialogue,
    duration_seconds: shot.duration_seconds,
    visual_prompt: shot.visual_prompt,
    camera_move: shot.camera_move,
  })
  const [warnings, setWarnings] = useState<ContinuityWarning[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [captureUrl, setCaptureUrl] = useState<string | null>(null)
  const [versionUrls, setVersionUrls] = useState<Record<number, string>>({})
  const [refineNote, setRefineNote] = useState('')
  const { hasDirectorProvider } = useAppSettings()

  useEffect(() => {
    setDraft({
      title: shot.title,
      description: shot.description,
      action: shot.action,
      dialogue: shot.dialogue,
      duration_seconds: shot.duration_seconds,
      visual_prompt: shot.visual_prompt,
      camera_move: shot.camera_move,
    })
  }, [shot.id, shot.updated_at, shot.title, shot.description, shot.action, shot.dialogue, shot.duration_seconds, shot.visual_prompt, shot.camera_move])

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    void filmApi
      .continuity(projectId, shot.id)
      .then(next => {
        if (!cancelled) setWarnings(next)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [projectId, shot.id, shot.updated_at])

  useEffect(() => {
    let cancelled = false
    if (shot.capture_path && projectId) {
      void filmMediaUrl(projectId, shot.capture_path).then(url => {
        if (!cancelled) setCaptureUrl(url)
      })
    } else {
      setCaptureUrl(null)
    }
    return () => {
      cancelled = true
    }
  }, [projectId, shot.capture_path, shot.updated_at])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const next: Record<number, string> = {}
      for (const version of shot.versions) {
        if (version.status === 'complete' && version.output_path) {
          next[version.number] = await filmOutputUrl(version.output_path)
        }
      }
      if (!cancelled) setVersionUrls(next)
    })()
    return () => {
      cancelled = true
    }
  }, [shot.versions])

  const saveDraft = useCallback(async () => {
    if (!projectId) return
    setBusy('save')
    try {
      await filmApi.updateShot(projectId, scene.id, shot.id, {
        title: draft.title,
        description: draft.description,
        action: draft.action,
        dialogue: draft.dialogue,
        duration_seconds: Math.max(0.5, draft.duration_seconds),
        camera_move: draft.camera_move,
        ...(draft.visual_prompt !== shot.visual_prompt
          ? { visual_prompt: draft.visual_prompt }
          : {}),
      })
      await refresh()
      setNote('Saved')
    } catch (e) {
      setNote(`Save failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [projectId, scene.id, shot.id, shot.visual_prompt, draft, refresh])

  const refinePrompt = useCallback(async () => {
    if (!projectId) return
    setBusy('refine')
    setRefineNote('')
    try {
      const result = await filmApi.refinePrompt(projectId, scene.id, shot.id)
      setRefineNote(`Refined by ${result.context.provider} · ${result.context.model}`)
      await refresh()
    } catch (e) {
      setRefineNote(`Refine failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [projectId, scene.id, shot.id, refresh])

  const unlockPrompt = useCallback(async () => {
    if (!projectId) return
    setBusy('unlock')
    try {
      await filmApi.updateShot(projectId, scene.id, shot.id, { prompt_locked: false })
      await refresh()
      setRefineNote('Prompt re-synthesized from shot fields')
    } catch (e) {
      setRefineNote(`Unlock failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [projectId, scene.id, shot.id, refresh])

  const generate = useCallback(
    async (kind: VersionKind) => {
      if (!projectId) return
      setBusy(kind)
      try {
        const result = await filmApi.generateShot(projectId, scene.id, shot.id, kind)
        setWarnings(result.warnings)
        setNote(kind === 'preview' ? 'Preview queued' : 'Final queued')
        await refresh()
      } catch (e) {
        setNote(`Generate failed: ${e instanceof Error ? e.message : e}`)
      } finally {
        setBusy(null)
      }
    },
    [projectId, scene.id, shot.id, refresh],
  )

  const setStatus = useCallback(
    async (status: FilmShot['status']) => {
      if (!projectId) return
      await filmApi.updateShot(projectId, scene.id, shot.id, { status })
      await refresh()
    },
    [projectId, scene.id, shot.id, refresh],
  )

  const promote = useCallback(
    async (number: number) => {
      if (!projectId) return
      await filmApi.promoteVersion(projectId, scene.id, shot.id, number)
      await refresh()
    },
    [projectId, scene.id, shot.id, refresh],
  )

  const currentVersion: ShotVersion | undefined = useMemo(
    () =>
      shot.current_version != null
        ? shot.versions.find(v => v.number === shot.current_version)
        : undefined,
    [shot.versions, shot.current_version],
  )

  const sendToTimeline = useCallback(async () => {
    if (!currentProjectId || !currentVersion || currentVersion.status !== 'complete') return
    setBusy('timeline')
    try {
      const copied = await copyToAssetFolder(currentVersion.output_path, currentProjectId)
      const path = copied?.path ?? currentVersion.output_path
      const url =
        copied?.url ??
        (path.startsWith('/') ? `file://${path}` : `file:///${path.replace(/\\/g, '/')}`)
      const asset: Asset = addAsset(currentProjectId, {
        type: 'video',
        path,
        url,
        prompt: currentVersion.prompt,
        resolution: currentVersion.resolution,
        duration: currentVersion.duration_seconds,
        generationParams: {
          mode: currentVersion.capture_path ? 'image-to-video' : 'text-to-video',
          prompt: currentVersion.prompt,
          model: currentVersion.model,
          duration: currentVersion.duration_seconds,
          resolution: currentVersion.resolution,
          fps: currentVersion.fps,
          audio: false,
          cameraMotion: 'none',
        },
        takes: [{ url, path, createdAt: Date.now() }],
        activeTakeIndex: 0,
      })

      const timeline = getActiveTimeline(currentProjectId)
      if (timeline) {
        const videoTrackIndex = Math.max(
          0,
          timeline.tracks.findIndex(t => t.kind === 'video' || t.kind === undefined),
        )
        const clipsOnTrack = timeline.clips.filter(c => c.trackIndex === videoTrackIndex)
        const endTime = clipsOnTrack.reduce(
          (max, clip) => Math.max(max, clip.startTime + clip.duration),
          0,
        )
        const gap = film?.settings.inter_shot_gap_seconds ?? 0
        const newClip: TimelineClip = {
          id: `clip-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
          assetId: asset.id,
          type: 'video',
          startTime: endTime > 0 ? endTime + gap : 0,
          duration: currentVersion.duration_seconds,
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
    } catch (e) {
      logger.error(`Send to timeline failed: ${e}`)
      setNote(`Send to timeline failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [currentProjectId, currentVersion, addAsset, getActiveTimeline, updateTimeline, film?.settings.inter_shot_gap_seconds])

  const status = SHOT_STATUS_META[shot.status]
  const videoModels = (capabilities?.models ?? []).filter(m => m.modes.includes('video'))

  return (
    <div className="w-[26rem] shrink-0 border-l border-zinc-800 bg-zinc-900/70 h-full overflow-y-auto">
      <div className="sticky top-0 z-10 flex items-center gap-2 px-3 py-2.5 border-b border-zinc-800 bg-zinc-900">
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${status.className}`}>
          {status.label}
        </span>
        <span className="flex-1 text-sm font-semibold text-white truncate">
          {shot.title || 'Shot'}
        </span>
        {note && <span className="text-[10px] text-zinc-500 truncate max-w-[8rem]">{note}</span>}
        <button
          onClick={onClose}
          aria-label="Close shot details"
          className="p-1 rounded hover:bg-zinc-800 text-zinc-400"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="p-3 space-y-3">
        {/* Composition preview + compose button */}
        <div className="rounded-lg overflow-hidden border border-zinc-800">
          <div className="aspect-video bg-zinc-950 flex items-center justify-center">
            {captureUrl ? (
              <img src={captureUrl} alt="Composition capture" className="w-full h-full object-cover" />
            ) : (
              <div className="text-center">
                <Aperture className="h-6 w-6 text-zinc-700 mx-auto mb-1" />
                <p className="text-[11px] text-zinc-600">No composition captured yet</p>
              </div>
            )}
          </div>
          <button
            onClick={onCompose}
            className="w-full flex items-center justify-center gap-1.5 py-2 bg-violet-700 hover:bg-violet-600 text-xs font-medium text-white"
          >
            <Aperture className="h-3.5 w-3.5" /> Compose Shot
          </button>
        </div>

        <div className="text-[11px] text-zinc-500">{framingLabel(shot.framing)}</div>

        {/* Continuity warnings */}
        {warnings.length > 0 && (
          <div className="rounded border border-amber-900/60 bg-amber-950/30 p-2 space-y-1">
            {warnings.map((warning, index) => (
              <div key={index} className="flex items-start gap-1.5 text-[11px] text-amber-300">
                <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
                {warning.message}
              </div>
            ))}
          </div>
        )}

        {/* Fields */}
        <div className="space-y-2">
          <Row label="Title">
            <input
              className={inputClass}
              value={draft.title}
              onChange={e => setDraft(d => ({ ...d, title: e.target.value }))}
            />
          </Row>
          <Row label="Action / what happens">
            <textarea
              className={`${inputClass} resize-none h-14`}
              value={draft.action}
              onChange={e => setDraft(d => ({ ...d, action: e.target.value }))}
            />
          </Row>
          <Row label="Dialogue">
            <textarea
              className={`${inputClass} resize-none h-10`}
              value={draft.dialogue}
              onChange={e => setDraft(d => ({ ...d, dialogue: e.target.value }))}
            />
          </Row>
          <div className="grid grid-cols-2 gap-2">
            <Row label="Duration (s)">
              <input
                type="number"
                min={0.5}
                step={0.5}
                className={inputClass}
                value={draft.duration_seconds}
                onChange={e => setDraft(d => ({ ...d, duration_seconds: Number(e.target.value) }))}
              />
            </Row>
            <Row label="Camera move">
              <select
                className={inputClass}
                value={draft.camera_move}
                onChange={e =>
                  setDraft(d => ({ ...d, camera_move: e.target.value as FilmShot['camera_move'] }))
                }
              >
                {CAMERA_MOVES.map(move => (
                  <option key={move.id} value={move.id}>
                    {move.label}
                  </option>
                ))}
              </select>
            </Row>
          </div>
          <Row label={shot.prompt_locked ? 'Visual prompt (edited — locked)' : 'Visual prompt (auto-synthesized)'}>
            <textarea
              className={`${inputClass} resize-none h-20 font-mono text-[10px] leading-snug`}
              value={draft.visual_prompt}
              onChange={e => setDraft(d => ({ ...d, visual_prompt: e.target.value }))}
            />
          </Row>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => void refinePrompt()}
              disabled={busy !== null || !hasDirectorProvider}
              className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[10px] text-violet-300"
              title={hasDirectorProvider ? 'Rewrite the prompt with the AI Director (keeps cast, wardrobe, framing)' : 'Needs an OpenRouter or Gemini key'}
            >
              {busy === 'refine' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wand2 className="h-3 w-3" />}
              Refine with AI
            </button>
            {shot.prompt_locked && (
              <button
                onClick={() => void unlockPrompt()}
                disabled={busy !== null}
                className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-400"
                title="Re-synthesize the prompt from the shot's structured fields"
              >
                Unlock & re-synthesize
              </button>
            )}
            {refineNote && <span className="text-[10px] text-zinc-500 truncate">{refineNote}</span>}
          </div>
          <Button size="sm" variant="secondary" onClick={() => void saveDraft()} disabled={busy !== null} className="w-full gap-1.5">
            {busy === 'save' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            Save shot
          </Button>
        </div>

        {/* Generation */}
        <div className="border-t border-zinc-800 pt-3 space-y-2">
          <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Generate</div>
          {videoModels.length > 0 && (
            <div className="text-[10px] text-zinc-600">
              {capabilities?.execution_mode === 'wangp'
                ? `WanGP · ${videoModels[0]?.id}`
                : capabilities?.execution_mode === 'api'
                  ? 'LTX cloud API'
                  : 'Local LTX pipeline'}
              {videoModels.some(m => m.fits_gpu === false) && (
                <span className="text-amber-400"> · VRAM may be insufficient (see Models)</span>
              )}
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={busy !== null || isGenerating}
              onClick={() => void generate('preview')}
              className="gap-1.5"
            >
              {busy === 'preview' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              Preview
            </Button>
            <Button
              size="sm"
              disabled={busy !== null || isGenerating}
              onClick={() => void generate('final')}
              className="gap-1.5"
            >
              {busy === 'final' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}
              Final
            </Button>
          </div>
          {isGenerating && (
            <div className="text-[10px] text-amber-400 flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" /> Generation in progress — new jobs queue behind it
            </div>
          )}
        </div>

        {/* Versions */}
        {shot.versions.length > 0 && (
          <div className="border-t border-zinc-800 pt-3 space-y-2">
            <div className="text-[10px] text-zinc-500 uppercase tracking-wide">
              Versions ({shot.versions.length})
            </div>
            {[...shot.versions].reverse().map(version => (
              <div
                key={version.number}
                className={`rounded border p-2 space-y-1.5 ${
                  shot.current_version === version.number
                    ? 'border-violet-700 bg-violet-950/20'
                    : 'border-zinc-800'
                }`}
              >
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="font-medium text-zinc-200">
                    v{version.number} · {version.kind}
                  </span>
                  <span
                    className={
                      version.status === 'complete'
                        ? 'text-emerald-400'
                        : version.status === 'failed'
                          ? 'text-red-400'
                          : 'text-amber-400'
                    }
                  >
                    {version.status}
                  </span>
                  <span className="flex-1" />
                  <span className="text-zinc-600">
                    {version.resolution} · {version.duration_seconds.toFixed(0)}s
                  </span>
                </div>
                {version.status === 'complete' && versionUrls[version.number] && (
                  <video
                    src={versionUrls[version.number]}
                    controls
                    playsInline
                    preload="metadata"
                    className="w-full rounded bg-black aspect-video"
                  />
                )}
                {version.status === 'failed' && (
                  <div className="text-[10px] text-red-400 break-words">{version.error}</div>
                )}
                <div className="flex gap-1">
                  {version.status === 'complete' && shot.current_version !== version.number && (
                    <button
                      onClick={() => void promote(version.number)}
                      className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300"
                    >
                      Set current
                    </button>
                  )}
                  {version.status === 'failed' && (
                    <button
                      onClick={() => void generate(version.kind)}
                      className="flex items-center gap-1 px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300"
                    >
                      <RefreshCw className="h-2.5 w-2.5" /> Retry
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Review actions */}
        {currentVersion?.status === 'complete' && (
          <div className="border-t border-zinc-800 pt-3 space-y-2">
            <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Review</div>
            <div className="grid grid-cols-2 gap-2">
              <Button
                size="sm"
                variant={shot.status === 'approved' ? 'default' : 'secondary'}
                onClick={() => void setStatus('approved')}
                className="gap-1.5"
              >
                <ThumbsUp className="h-3.5 w-3.5" /> Approve
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void setStatus('rejected')}
                className="gap-1.5"
              >
                <ThumbsDown className="h-3.5 w-3.5" /> Reject
              </Button>
            </div>
            <Button
              size="sm"
              onClick={() => void sendToTimeline()}
              disabled={busy !== null}
              className="w-full gap-1.5"
            >
              {busy === 'timeline' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              Send to Timeline
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
