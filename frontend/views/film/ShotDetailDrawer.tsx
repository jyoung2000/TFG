import { useCallback, useEffect, useState } from 'react'
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
import { useFilm } from '../../contexts/FilmContext'
import { filmApi, filmMediaUrl, filmOutputUrl } from '../../lib/film-api'
import { useUiMode } from '../../lib/ui-mode'
import { Button } from '../../components/ui/button'
import type {
  ContinuityLevel,
  ContinuityWarning,
  FilmScene,
  FilmShot,
  QualityPreset,
  VersionKind,
} from '../../types/film'
import { CAMERA_MOVES, CONTINUITY_LEVEL_META, SHOT_STATUS_META, framingLabel } from '../../types/film'
import { useShotWorkflow } from './useShotWorkflow'

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
  const { film, refresh, capabilities, isGenerating, setShotContinuity } = useFilm()
  const workflow = useShotWorkflow(scene, shot)
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
  const [continuityLevel, setContinuityLevel] = useState<ContinuityLevel>('good')
  const [fixNote, setFixNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [captureUrl, setCaptureUrl] = useState<string | null>(null)
  const [versionUrls, setVersionUrls] = useState<Record<number, string>>({})
  const [refineNote, setRefineNote] = useState('')
  const { hasDirectorProvider } = useAppSettings()
  const [uiMode] = useUiMode()

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
        if (!cancelled) {
          setWarnings(next.warnings)
          setContinuityLevel(next.level)
          setShotContinuity(shot.id, next.level, next.warnings.length)
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [projectId, shot.id, shot.updated_at, setShotContinuity])

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

  const fixWarning = useCallback(
    async (warning: ContinuityWarning) => {
      if (!projectId) return
      setBusy('fix')
      setFixNote('')
      try {
        const result = await filmApi.fixContinuity(projectId, shot.id, warning.kind, warning.subject_id)
        setWarnings(result.report.warnings)
        setContinuityLevel(result.report.level)
        setShotContinuity(shot.id, result.report.level, result.report.warnings.length)
        setFixNote(result.message)
        await refresh()
      } catch (e) {
        setFixNote(`Fix failed: ${e instanceof Error ? e.message : e}`)
      } finally {
        setBusy(null)
      }
    },
    [projectId, shot.id, refresh, setShotContinuity],
  )

  const setQualityPreset = useCallback(
    async (preset: QualityPreset) => {
      if (!projectId) return
      setBusy('preset')
      try {
        await filmApi.updateShot(projectId, scene.id, shot.id, {
          generation: { ...shot.generation, quality_preset: preset },
        })
        await refresh()
      } catch (e) {
        setNote(`Preset failed: ${e instanceof Error ? e.message : e}`)
      } finally {
        setBusy(null)
      }
    },
    [projectId, scene.id, shot.id, shot.generation, refresh],
  )

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
      const result = await workflow.generate(kind)
      if (result) {
        setWarnings(result)
        setContinuityLevel(
          result.reduce<ContinuityLevel>((worst, w) => {
            const rank: Record<ContinuityLevel, number> = { good: 0, minor: 1, significant: 2, broken: 3 }
            return rank[w.severity] > rank[worst] ? w.severity : worst
          }, 'good'),
        )
      }
    },
    [workflow],
  )

  const { setStatus, promote, currentVersion, sendToTimeline, linkedClip, queueInfo } = workflow
  // The drawer's own busy flag covers its edits; the workflow hook covers generation/hand-off.
  const anyBusy = busy !== null || workflow.busy !== null
  const displayNote = note || workflow.note

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
        {displayNote && (
          <span className="text-[10px] text-zinc-500 truncate max-w-[8rem]" role="status">
            {displayNote}
          </span>
        )}
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

        {/* Continuity level + warnings with fixes */}
        <div
          className={`rounded border p-2 space-y-1.5 ${
            continuityLevel === 'good'
              ? 'border-emerald-900/50 bg-emerald-950/20'
              : continuityLevel === 'minor'
                ? 'border-amber-900/60 bg-amber-950/30'
                : continuityLevel === 'significant'
                  ? 'border-orange-900/60 bg-orange-950/30'
                  : 'border-red-900/60 bg-red-950/30'
          }`}
          role="status"
        >
          <div className={`flex items-center gap-1.5 text-[11px] font-medium ${CONTINUITY_LEVEL_META[continuityLevel].text}`}>
            <span className={`inline-block h-2 w-2 rounded-full ${CONTINUITY_LEVEL_META[continuityLevel].dot}`} />
            {CONTINUITY_LEVEL_META[continuityLevel].label}
            <span className="ml-auto text-[10px] uppercase tracking-wide opacity-70">{continuityLevel}</span>
          </div>
          {warnings.map((warning, index) => (
            <div key={index} className="text-[11px] text-zinc-300">
              <div className="flex items-start gap-1.5">
                <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0 text-amber-300" />
                <span className="flex-1">{warning.message}</span>
              </div>
              <div className="flex items-center gap-2 ml-4.5 pl-[18px] mt-0.5">
                <span className="text-[10px] text-zinc-500 flex-1">{warning.fix}</span>
                {warning.auto_fixable && (
                  <button
                    onClick={() => void fixWarning(warning)}
                    disabled={busy !== null}
                    className="px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[10px] text-emerald-300"
                  >
                    {busy === 'fix' ? 'Fixing…' : 'Fix'}
                  </button>
                )}
              </div>
            </div>
          ))}
          {fixNote && <div className="text-[10px] text-zinc-400">{fixNote}</div>}
        </div>

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
          {uiMode === 'advanced' && capabilities && capabilities.profiles.length > 0 && (
            <Row label="Quality profile (final renders)">
              <select
                className={inputClass}
                value={shot.generation.quality_preset}
                disabled={busy !== null}
                onChange={e => void setQualityPreset(e.target.value as QualityPreset)}
                aria-label="Quality profile"
              >
                <option value="project">
                  Project default ({film?.settings.default_quality_preset ?? 'balanced'})
                </option>
                {capabilities.profiles.map(profile => (
                  <option key={profile.id} value={profile.id}>
                    {profile.label}
                    {profile.model ? ` · ${profile.model} @ ${profile.resolution}` : ''}
                    {profile.recommended ? ' · recommended for this GPU' : ''}
                    {profile.fits_gpu === false ? ' · may not fit VRAM' : ''}
                  </option>
                ))}
              </select>
            </Row>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={anyBusy || queueInfo.active || queueInfo.pendingPosition != null}
              onClick={() => void generate('preview')}
              className="gap-1.5"
            >
              {workflow.busy === 'preview' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              Preview
            </Button>
            <Button
              size="sm"
              disabled={anyBusy || queueInfo.active || queueInfo.pendingPosition != null}
              onClick={() => void generate('final')}
              className="gap-1.5"
            >
              {workflow.busy === 'final' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}
              Final
            </Button>
          </div>
          {(queueInfo.active || queueInfo.pendingPosition != null) && (
            <div className="space-y-1">
              <div className="text-[10px] text-amber-400 flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                {queueInfo.active
                  ? `Rendering this shot${queueInfo.progress != null ? ` · ${Math.round(queueInfo.progress)}%` : ''}${queueInfo.phase ? ` · ${queueInfo.phase}` : ''}`
                  : `Queued · position ${queueInfo.pendingPosition}`}
                <button
                  onClick={() => void workflow.cancelJob()}
                  className="ml-auto px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300"
                >
                  Cancel
                </button>
              </div>
              {queueInfo.active && queueInfo.progress != null && (
                <div className="h-1 rounded bg-zinc-800 overflow-hidden">
                  <div className="h-full bg-violet-500 transition-all" style={{ width: `${Math.min(100, Math.max(0, queueInfo.progress))}%` }} />
                </div>
              )}
            </div>
          )}
          {isGenerating && !queueInfo.active && queueInfo.pendingPosition == null && (
            <div className="text-[10px] text-zinc-500 flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" /> Another shot is rendering — new jobs queue behind it
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
                    {version.generation_seconds != null ? ` · ${version.generation_seconds.toFixed(0)}s render` : ''}
                    {version.execution_mode ? ` · ${version.execution_mode}` : ''}
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
                      disabled={anyBusy}
                      className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[10px] text-zinc-300"
                    >
                      Set current
                    </button>
                  )}
                  {version.status === 'complete' && (
                    <button
                      onClick={() => void sendToTimeline(version)}
                      disabled={anyBusy}
                      className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[10px] text-zinc-300"
                      title="Add this version to the timeline as a new clip"
                    >
                      To timeline
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
              onClick={() => void sendToTimeline(currentVersion, { replace: linkedClip !== null })}
              disabled={anyBusy}
              className="w-full gap-1.5"
            >
              {workflow.busy === 'timeline' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              {linkedClip ? `Replace timeline clip with v${currentVersion.number}` : 'Send to Timeline'}
            </Button>
            {linkedClip && (
              <button
                onClick={() => void sendToTimeline(currentVersion)}
                disabled={anyBusy}
                className="w-full text-[10px] text-zinc-500 hover:text-zinc-300"
              >
                or add as a new clip
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
