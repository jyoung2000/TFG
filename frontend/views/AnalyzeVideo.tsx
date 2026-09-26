import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CompiledPrompts } from '../components/CompiledPrompts'
import {
  ArrowLeft,
  Clapperboard,
  FileVideo,
  Loader2,
  Scissors,
  Sparkles,
  Trash2,
  Video,
  Wand2,
  X,
} from 'lucide-react'
import { useProjects } from '../contexts/ProjectContext'
import { useFilm } from '../contexts/FilmContext'
import { useAppSettings } from '../contexts/AppSettingsContext'
import { filmApi } from '../lib/film-api'
import type { FilmModelCapability } from '../types/film'
import { analysisFrameUrl, videoAnalysisApi } from '../lib/video-analysis-api'
import { videoReproduceApi } from '../lib/video-reproduce-api'
import { sceneApi } from '../lib/scene-api'
import type { VideoReproduceJob } from '../types/video-reproduce'
import { VideoReproducePanel } from './reproduce/VideoReproduce'
import { logger } from '../lib/logger'
import {
  DETECTION_METHOD_META,
  STAGE_META,
  confidenceLabel,
  type AnalysisDepth,
  type AnalyzedShot,
  type VideoAnalysis,
} from '../types/video-analysis'

/**
 * Analyse Video — the reverse of the filmmaking flow.
 *
 * Import → Detect shots → Analyse → Review → Create storyboard.
 *
 * The screen's job is to keep the user's trust in what it is telling them:
 * every inferred field shows its confidence, an arbitrary boundary says so,
 * and the frames that produced a reading stay one click away. Detection works
 * with no provider at all, so the first three steps never wait on a key.
 */
export function AnalyzeVideo() {
  const { setCurrentView, openProject, pendingAnalysis, clearPendingAnalysis } = useProjects()
  const { setCurrentProjectId } = useProjects()
  const { refresh } = useFilm()
  const { settings } = useAppSettings()
  const [videoModels, setVideoModels] = useState<FilmModelCapability[]>([])
  useEffect(() => {
    void filmApi.capabilities()
      .then(result => setVideoModels(result.models.filter(m => m.modes.includes('video') && m.downloaded)))
      .catch(() => undefined)
  }, [])

  const [analyses, setAnalyses] = useState<VideoAnalysis[]>([])
    const [current, setCurrent] = useState<VideoAnalysis | null>(null)
    const [selectedShotId, setSelectedShotId] = useState<string | null>(null)
    const [busy, setBusy] = useState<string>('')
    const [error, setError] = useState('')
  
    // Video Reproduce v2: the backend document for the current analysis.
    const [recreating, setRecreating] = useState(false)
    const [reproduce, setReproduce] = useState<VideoReproduceJob | null>(null)
    const [recreationCandidates, setRecreationCandidates] = useState(2)
    const [recreationRounds] = useState(1)
    useEffect(() => {
      setReproduce(null)
      if (!current) return
      let active = true
      videoReproduceApi.get(current.id)
        .then(job => { if (active && job.status !== 'idle') setReproduce(job) })
        .catch(() => undefined)
      return () => { active = false }
    }, [current?.id])  // eslint-disable-line react-hooks/exhaustive-deps

    const [depth, setDepth] = useState<AnalysisDepth>('standard')
  const [sensitivity, setSensitivity] = useState(0.5)
  const [minShot, setMinShot] = useState(0.6)
  const [analyzeAudio, setAnalyzeAudio] = useState(false)
  const [analyzeText, setAnalyzeText] = useState(false)

  const loadList = useCallback(async () => {
    try {
      setAnalyses(await videoAnalysisApi.list())
    } catch (e) {
      logger.warn(`Could not list analyses: ${e}`)
    }
  }, [])

  useEffect(() => {
    void loadList()
  }, [loadList])

  // Opened from History with a specific analysis: load it, then forget the request.
  useEffect(() => {
    if (!pendingAnalysis || pendingAnalysis.kind !== 'video') return
    const id = pendingAnalysis.id
    clearPendingAnalysis()
    void videoAnalysisApi.get(id).then(setCurrent).catch(e => logger.warn(`Could not open analysis ${id}: ${e}`))
  }, [pendingAnalysis, clearPendingAnalysis])

  // While a stage is running the backend owns the truth, so poll it rather
  // than guessing progress on this side.
  const stage = current ? STAGE_META[current.stage] : null
  useEffect(() => {
    if (!current || !stage?.busy) return
    const id = window.setInterval(async () => {
      try {
        setCurrent(await videoAnalysisApi.get(current.id))
      } catch {
        /* a deleted analysis simply stops updating */
      }
    }, 900)
    return () => window.clearInterval(id)
  }, [current, stage?.busy])

  const run = useCallback(
    async (label: string, work: () => Promise<VideoAnalysis>) => {
      setBusy(label)
      setError('')
      try {
        const updated = await work()
        setCurrent(updated)
        await loadList()
        return updated
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        return null
      } finally {
        setBusy('')
      }
    },
    [loadList],
  )

  const pickAndImport = useCallback(async () => {
    const picked = await window.electronAPI
      .showOpenFileDialog({
        title: 'Choose a video to analyse',
        filters: [{ name: 'Video', extensions: ['mp4', 'mov', 'mkv', 'webm', 'm4v', 'avi'] }],
        properties: ['openFile'],
      })
      .catch(() => null)
    const path = picked?.[0]
    if (!path) return
    await run('import', () =>
      videoAnalysisApi.importVideo({
        path,
        depth,
        sensitivity,
        min_shot_seconds: minShot,
        analyze_audio: analyzeAudio,
        analyze_text: analyzeText,
      }),
    )
  }, [analyzeAudio, analyzeText, depth, minShot, run, sensitivity])

  const createStoryboard = useCallback(async () => {
      if (!current) return
      setBusy('reconstruct')
      setError('')
      try {
        const project = await videoAnalysisApi.reconstruct(current.id, {
          name: current.title ? `${current.title} (from video)` : '',
        })
        setCurrentProjectId(project.id)
        await refresh()
        openProject(project.id, 'storyboard')
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy('')
      }
    }, [current, openProject, refresh, setCurrentProjectId])

    const buildStoryboard3d = useCallback(async () => {
      if (!current) return
      setBusy('storyboard3d')
      setError('')
      try {
        const project = await sceneApi.storyboard3d(current.id, { name: current.title ? `${current.title} (3D storyboard)` : '' })
        setCurrentProjectId(project.id)
        await refresh()
        openProject(project.id, 'storyboard')
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy('')
      }
    }, [current, openProject, refresh, setCurrentProjectId])

    const recreateVideo = useCallback(async () => {
      if (!current) return
      setRecreating(true)
      setError('')
      try {
        await videoReproduceApi.start(current.id, { candidates: recreationCandidates, rounds: recreationRounds, shot_ids: [] })
        setReproduce(await videoReproduceApi.get(current.id))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setRecreating(false)
      }
    }, [current, recreationCandidates, recreationRounds])

    const selected = useMemo(
    () => current?.shots.find(shot => shot.id === selectedShotId) ?? current?.shots[0] ?? null,
    [current, selectedShotId],
  )

  return (
    <div className="h-screen flex flex-col bg-zinc-950 text-zinc-200">
      <header className="flex items-center gap-3 px-4 h-14 border-b border-zinc-800 shrink-0">
        <button
          onClick={() => setCurrentView('home')}
          aria-label="Back to home"
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <FileVideo className="h-4 w-4 text-violet-400" />
        <h1 className="text-sm font-semibold text-white">Analyse video</h1>
        {current && (
          <>
            <span className="text-xs text-zinc-500 truncate max-w-[24rem]">{current.source.file_name}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${STAGE_META[current.stage].className}`}>
              {STAGE_META[current.stage].label}
            </span>
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          {stage?.busy && (
            <>
              <span className="text-[11px] text-zinc-400">
                {current?.message} {Math.round((current?.progress ?? 0) * 100)}%
              </span>
              <button
                onClick={() => current && void run('cancel', () => videoAnalysisApi.cancel(current.id))}
                className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-[11px] hover:bg-zinc-700"
              >
                <X className="h-3 w-3" /> Cancel
              </button>
            </>
          )}
        </div>
      </header>

      {error && (
        <div role="alert" className="mx-4 mt-3 rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-300">
          {error}
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        <aside className="w-72 shrink-0 border-r border-zinc-800 overflow-y-auto p-3 space-y-4">
          <ImportPanel
            busy={busy === 'import'}
            depth={depth}
            setDepth={setDepth}
            sensitivity={sensitivity}
            setSensitivity={setSensitivity}
            minShot={minShot}
            setMinShot={setMinShot}
            analyzeAudio={analyzeAudio}
            setAnalyzeAudio={setAnalyzeAudio}
            analyzeText={analyzeText}
            setAnalyzeText={setAnalyzeText}
            onPick={() => void pickAndImport()}
          />

          {analyses.length > 0 && (
            <section className="space-y-1">
              <h2 className="text-[11px] uppercase tracking-wide text-zinc-500">Recent</h2>
              {analyses.map(item => (
                <div key={item.id} className="flex items-center gap-1">
                  <button
                    onClick={() => {
                      setCurrent(item)
                      setSelectedShotId(null)
                    }}
                    className={`flex-1 text-left px-2 py-1.5 rounded text-xs truncate ${
                      current?.id === item.id ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:bg-zinc-900'
                    }`}
                  >
                    {item.title}
                    <span className="block text-[10px] text-zinc-600">
                      {item.shots.length} shot{item.shots.length === 1 ? '' : 's'} · {STAGE_META[item.stage].label}
                    </span>
                  </button>
                  <button
                    onClick={async () => {
                      await videoAnalysisApi.remove(item.id).catch(() => {})
                      if (current?.id === item.id) setCurrent(null)
                      void loadList()
                    }}
                    aria-label={`Delete the analysis of ${item.title}`}
                    className="p-1 rounded text-zinc-600 hover:text-red-300"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </section>
          )}
        </aside>

        {!current ? (
          <EmptyState />
        ) : (
          <>
            <section className="flex-1 min-w-0 overflow-y-auto p-4 space-y-4">
              <SourceSummary analysis={current} />
              <div className="flex flex-wrap items-center gap-2">
                              <button
                                onClick={() => void run('detect', () => videoAnalysisApi.detect(current.id))}
                                disabled={busy !== '' || stage?.busy}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 text-xs hover:bg-zinc-700 disabled:opacity-40"
                              >
                                {busy === 'detect' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />}
                                {current.shots.length ? 'Detect again' : 'Detect shots'}
                              </button>
                              <button
                                onClick={() => void run('analyze', () => videoAnalysisApi.analyze(current.id))}
                                disabled={busy !== '' || stage?.busy || current.shots.length === 0}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600 text-white text-xs hover:bg-violet-500 disabled:bg-zinc-700 disabled:text-zinc-500"
                              >
                                {busy === 'analyze' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                                Analyse shots
                              </button>
                              <label className="flex items-center gap-1 text-[11px] text-zinc-400">
                                Candidates
                                <input type="number" min={1} max={6} value={recreationCandidates} onChange={e => setRecreationCandidates(Math.max(1, Math.min(6, Number(e.target.value) || 1)))} aria-label="Candidates per shot" className="select-chip w-14" />
                              </label>
                              <button
                                onClick={() => void recreateVideo()}
                                disabled={busy !== '' || recreating || reproduce?.status === 'running' || current.shots.length === 0}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs hover:bg-emerald-500 disabled:bg-zinc-700 disabled:text-zinc-500"
                              >
                                {recreating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Video className="h-3.5 w-3.5" />}
                                Recreate video
                              </button>
                              <button
                                onClick={() => void createStoryboard()}
                                disabled={busy !== '' || current.shots.length === 0}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 text-xs hover:bg-zinc-700 disabled:opacity-40"
                              >
                                {busy === 'reconstruct' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Clapperboard className="h-3.5 w-3.5" />}
                                Create storyboard
                              </button>
                              <button
                                onClick={() => void buildStoryboard3d()}
                                disabled={busy !== '' || current.shots.length === 0 || current.stage !== 'complete'}
                                title="A film project whose shot cards carry 3D blockouts and open the composer pre-seeded from the analysis"
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 text-xs hover:bg-zinc-700 disabled:opacity-40"
                              >
                                {busy === 'storyboard3d' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Clapperboard className="h-3.5 w-3.5" />}
                                Build 3D storyboard
                              </button>
                              <span className="text-[11px] text-zinc-400" data-testid="video-model-recommendation">
                                Vision: {settings.directorProvider === 'openai_compatible' && settings.openaiCompatibleModel ? settings.openaiCompatibleModel : 'connect qwen2.5vl:7b (recommended) in Settings'}
                                {' · '}Recommended render model: {videoModels.find(m => m.is_active)?.label || videoModels[0]?.label || 'no local video model detected'}
                              </span>
                            </div>

              <ShotStrip
                analysis={current}
                selectedId={selected?.id ?? null}
                onSelect={setSelectedShotId}
              />
            </section>

            {selected && (
                          <ShotInspector
                            analysis={current}
                            shot={selected}
                            busy={busy}
                            onSplit={at => void run('split', () => videoAnalysisApi.split(current.id, selected.id, at))}
                            onMerge={() => void run('merge', () => videoAnalysisApi.merge(current.id, selected.id))}
                            onEditPrompts={prompts => void run('prompts', () => videoAnalysisApi.editPrompts(current.id, selected.id, prompts))}
                          />
                        )}
            
                        {reproduce && (
                          <VideoReproducePanel analysis={current} job={reproduce} onJob={setReproduce} onClose={() => setReproduce(null)} onBuild3D={() => void buildStoryboard3d()} />
                        )}
                      </>
                    )}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="max-w-md text-center space-y-3">
        <FileVideo className="h-10 w-10 text-zinc-700 mx-auto" />
        <h2 className="text-base font-semibold text-white">Turn an existing video into a storyboard</h2>
        <p className="text-sm text-zinc-500 leading-relaxed">
          Import a clip and TFG finds its shots, reads their framing and camera language, and builds an editable film
          project you can change and regenerate. Finding the shots needs nothing but this computer.
        </p>
      </div>
    </div>
  )
}

function ImportPanel(props: {
  busy: boolean
  depth: AnalysisDepth
  setDepth: (value: AnalysisDepth) => void
  sensitivity: number
  setSensitivity: (value: number) => void
  minShot: number
  setMinShot: (value: number) => void
  analyzeAudio: boolean
  setAnalyzeAudio: (value: boolean) => void
  analyzeText: boolean
  setAnalyzeText: (value: boolean) => void
  onPick: () => void
}) {
  return (
    <section className="space-y-2">
      <button
        onClick={props.onPick}
        disabled={props.busy}
        className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-violet-600 text-white text-xs font-medium hover:bg-violet-500 disabled:bg-zinc-700"
      >
        {props.busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileVideo className="h-4 w-4" />}
        Import a video
      </button>

      <details className="rounded-lg border border-zinc-800 bg-zinc-900/60">
        <summary className="px-2.5 py-1.5 text-[11px] text-zinc-400 cursor-pointer select-none">Analysis options</summary>
        <div className="p-2.5 pt-1 space-y-2.5">
          <label className="block text-[11px] text-zinc-400">
            Depth
            <select
              value={props.depth}
              onChange={e => props.setDepth(e.target.value as AnalysisDepth)}
              className="mt-1 w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200"
            >
              <option value="fast">Fast — fewer samples, one frame a shot</option>
              <option value="standard">Standard</option>
              <option value="detailed">Detailed — denser sampling, three frames a shot</option>
            </select>
          </label>

          <label className="block text-[11px] text-zinc-400">
            Shot sensitivity: {props.sensitivity.toFixed(2)}
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={props.sensitivity}
              onChange={e => props.setSensitivity(Number(e.target.value))}
              className="mt-1 w-full accent-violet-500"
            />
            <span className="text-[10px] text-zinc-600">Higher finds more cuts.</span>
          </label>

          <label className="block text-[11px] text-zinc-400">
            Shortest shot (seconds)
            <input
              type="number"
              min={0.1}
              step={0.1}
              value={props.minShot}
              onChange={e => props.setMinShot(Number(e.target.value))}
              className="mt-1 w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200"
            />
          </label>

          <label className="flex items-center gap-2 text-[11px] text-zinc-400">
            <input type="checkbox" checked={props.analyzeAudio} onChange={e => props.setAnalyzeAudio(e.target.checked)} />
            Analyse audio when the file has some
          </label>
          <label className="flex items-center gap-2 text-[11px] text-zinc-400">
            <input type="checkbox" checked={props.analyzeText} onChange={e => props.setAnalyzeText(e.target.checked)} />
            Read on-screen text
          </label>
        </div>
      </details>
    </section>
  )
}

function SourceSummary({ analysis }: { analysis: VideoAnalysis }) {
  const source = analysis.source
  const facts: [string, string][] = [
    ['Duration', `${source.duration_seconds.toFixed(1)}s`],
    ['Resolution', source.width ? `${source.width}×${source.height}` : '—'],
    ['Aspect', source.aspect_ratio || '—'],
    ['Frame rate', source.fps ? `${source.fps.toFixed(2)} fps` : '—'],
    ['Codec', source.codec || '—'],
    ['Audio', source.has_audio ? source.audio_codec || 'yes' : 'none'],
  ]
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <div className="grid grid-cols-3 gap-y-2 gap-x-4 sm:grid-cols-6">
        {facts.map(([label, value]) => (
          <div key={label}>
            <div className="text-[10px] uppercase tracking-wide text-zinc-600">{label}</div>
            <div className="text-xs text-zinc-200">{value}</div>
          </div>
        ))}
      </div>
      {analysis.synopsis && <p className="mt-3 text-xs text-zinc-400 leading-relaxed">{analysis.synopsis}</p>}
    </div>
  )
}

function ShotStrip({
  analysis,
  selectedId,
  onSelect,
}: {
  analysis: VideoAnalysis
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  if (analysis.shots.length === 0) {
    return (
      <p className="text-xs text-zinc-500">
        No shots yet — run <span className="text-zinc-300">Detect shots</span> to find them.
      </p>
    )
  }
  return (
    <div className="flex flex-wrap gap-3">
      {analysis.shots.map(shot => (
        <ShotCard
          key={shot.id}
          analysisId={analysis.id}
          shot={shot}
          selected={shot.id === selectedId}
          onSelect={() => onSelect(shot.id)}
        />
      ))}
    </div>
  )
}

function ShotCard({
  analysisId,
  shot,
  selected,
  onSelect,
}: {
  analysisId: string
  shot: AnalyzedShot
  selected: boolean
  onSelect: () => void
}) {
  const frame = shot.frames[0]
  const url = useFrameUrl(analysisId, frame?.path)
  const method = DETECTION_METHOD_META[shot.detection_method]
  return (
    <button
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`Shot ${shot.index + 1}, ${shot.start.toFixed(1)} to ${shot.end.toFixed(1)} seconds`}
      className={`w-44 rounded-lg border overflow-hidden text-left transition-colors ${
        selected ? 'border-violet-500' : 'border-zinc-800 hover:border-zinc-600'
      }`}
    >
      <div className="relative aspect-video bg-zinc-950 flex items-center justify-center">
        {url ? <img src={url} alt="" className="w-full h-full object-cover" /> : <FileVideo className="h-5 w-5 text-zinc-700" />}
        <span className="absolute top-1 left-1 px-1.5 py-0.5 rounded bg-black/70 text-[10px] text-zinc-200">
          {shot.index + 1}
        </span>
        {shot.boundary_edited && (
          <span className="absolute top-1 right-1 px-1.5 py-0.5 rounded bg-violet-900/80 text-[9px] text-violet-200">
            edited
          </span>
        )}
      </div>
      <div className="p-2 space-y-0.5">
        <div className="text-[11px] text-zinc-300">
          {shot.start.toFixed(2)}s – {shot.end.toFixed(2)}s
          <span className="text-zinc-600"> · {shot.duration.toFixed(2)}s</span>
        </div>
        <div className="text-[10px] text-zinc-600" title={method.hint}>
          {method.label}
          {shot.detection_method === 'uniform' && ' (arbitrary)'}
        </div>
        {shot.visual.description && <div className="text-[10px] text-zinc-500 line-clamp-2">{shot.visual.description}</div>}
      </div>
    </button>
  )
}

/** Resolve a frame path into an authenticated URL. */
function useFrameUrl(analysisId: string, framePath: string | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null)
  const latest = useRef(0)
  useEffect(() => {
    if (!framePath) {
      setUrl(null)
      return
    }
    const epoch = ++latest.current
    void analysisFrameUrl(analysisId, framePath).then(resolved => {
      if (latest.current === epoch) setUrl(resolved)
    })
  }, [analysisId, framePath])
  return url
}

function ShotInspector({
  analysis,
  shot,
  busy,
  onSplit,
  onMerge,
  onEditPrompts,
}: {
  analysis: VideoAnalysis
  shot: AnalyzedShot
  busy: string
  onSplit: (at: number) => void
  onMerge: () => void
  onEditPrompts: (prompts: Record<string, string>) => void
}) {
  const [splitAt, setSplitAt] = useState(() => (shot.start + shot.end) / 2)
  useEffect(() => setSplitAt((shot.start + shot.end) / 2), [shot.id, shot.start, shot.end])

  const inferred = shot.provenance !== 'measured'
  return (
    <aside className="w-96 shrink-0 border-l border-zinc-800 overflow-y-auto p-3 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-white">Shot {shot.index + 1}</h2>
        <p className="text-[11px] text-zinc-500">
          {shot.start.toFixed(2)}s – {shot.end.toFixed(2)}s · {DETECTION_METHOD_META[shot.detection_method].label}
          {shot.detection_confidence > 0 && ` · ${confidenceLabel(shot.detection_confidence)}`}
        </p>
      </div>

      <section className="space-y-1.5">
        <h3 className="text-[11px] uppercase tracking-wide text-zinc-500">Evidence</h3>
        <div className="flex gap-1.5 flex-wrap">
          {shot.frames.map(frame => (
            <FrameThumb key={frame.path} analysisId={analysis.id} path={frame.path} timestamp={frame.timestamp} role={frame.role} />
          ))}
          {shot.frames.length === 0 && <p className="text-[11px] text-zinc-600">No frames extracted yet.</p>}
        </div>
      </section>

      <section className="space-y-1.5">
        <h3 className="text-[11px] uppercase tracking-wide text-zinc-500">Boundaries</h3>
        <div className="flex items-center gap-1.5">
          <input
            type="number"
            step={0.1}
            min={shot.start + 0.05}
            max={shot.end - 0.05}
            value={Number.isFinite(splitAt) ? Number(splitAt.toFixed(2)) : 0}
            onChange={e => setSplitAt(Number(e.target.value))}
            aria-label="Split this shot at (seconds)"
            className="w-24 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs"
          />
          <button
            onClick={() => onSplit(splitAt)}
            disabled={busy !== ''}
            className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-[11px] hover:bg-zinc-700 disabled:opacity-40"
          >
            Split here
          </button>
          <button
            onClick={onMerge}
            disabled={busy !== '' || shot.index >= analysis.shots.length - 1}
            title="Join this shot with the one after it"
            className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-[11px] hover:bg-zinc-700 disabled:opacity-40"
          >
            Merge next
          </button>
        </div>
      </section>

      <AnalysisGroup
        title="What the model saw"
        confidence={shot.visual.confidence}
        inferred={inferred}
        rows={[
          ['Description', shot.visual.description],
          ['Shot size', shot.visual.shot_size],
          ['Angle', shot.visual.angle],
          ['Location', shot.visual.location],
          ['Lighting', shot.visual.lighting],
          ['Subjects', shot.visual.subjects.join(', ')],
        ]}
      />
      <AnalysisGroup
        title="Camera"
        confidence={shot.cinematography.confidence}
        inferred={inferred}
        rows={[
          ['Movement', shot.cinematography.camera_movement],
          ['Measured motion', shot.motion?.analyzed ? `${shot.motion.pacing} · magnitude ${shot.motion.magnitude.toFixed(3)}${shot.motion.handheld ? ' · handheld' : ''} (${shot.motion.model})` : 'not measured'],
          ['Static', shot.cinematography.is_static ? 'yes' : 'no'],
          ['Screen direction', shot.cinematography.screen_direction],
        ]}
      />
      <PromptLensPanel lens={shot.prompt_lens} />
      <AnalysisGroup
        title="Editorial (measured)"
        confidence={shot.editorial.confidence}
        inferred={false}
        rows={[
          ['Cut type', shot.editorial.cut_type],
          ['Rhythm', shot.editorial.rhythm],
          ['Beat', shot.editorial.approximate_beat],
        ]}
      />

      <PromptEditor shot={shot} busy={busy !== ''} onSave={onEditPrompts} />

      {/* The same shot, written the way each model wants to hear it. Keyed on
          the shot so switching shots recompiles rather than showing the last
          one's prompts. */}
      <CompiledPrompts
        key={shot.id}
        source={{ analysis_id: analysis.id, analysis_shot_id: shot.id }}
        models={Object.keys(shot.prompts.model_specific)}
      />

      {shot.evidence_note && (
        <details className="rounded border border-zinc-800 bg-zinc-900/60">
          <summary className="px-2 py-1.5 text-[11px] text-zinc-400 cursor-pointer">Why did the AI write this?</summary>
          <pre className="p-2 text-[10px] text-zinc-500 whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
            {shot.evidence_note}
          </pre>
          <p className="px-2 pb-2 text-[10px] text-zinc-600">
            {shot.analysis_provider === 'deterministic'
              ? 'Measured from the file — no model was involved.'
              : `From ${shot.analysis_provider} ${shot.analysis_model}.`}
          </p>
        </details>
      )}
    </aside>
  )
}

function FrameThumb({
  analysisId,
  path,
  timestamp,
  role,
}: {
  analysisId: string
  path: string
  timestamp: number
  role: string
}) {
  const url = useFrameUrl(analysisId, path)
  return (
    <figure className="w-[5.5rem]">
      {url ? (
        <img src={url} alt={`${role} frame at ${timestamp.toFixed(2)} seconds`} className="w-full rounded border border-zinc-800" />
      ) : (
        <div className="w-full aspect-video rounded border border-zinc-800 bg-zinc-900" />
      )}
      <figcaption className="text-[9px] text-zinc-600 mt-0.5">
        {role} · {timestamp.toFixed(2)}s
      </figcaption>
    </figure>
  )
}

function AnalysisGroup({
  title,
  confidence,
  inferred,
  rows,
}: {
  title: string
  confidence: number
  inferred: boolean
  rows: [string, string][]
}) {
  const filled = rows.filter(([, value]) => value)
  if (filled.length === 0) return null
  return (
    <section className="space-y-1">
      <h3 className="text-[11px] uppercase tracking-wide text-zinc-500 flex items-center gap-2">
        {title}
        <span className={`text-[9px] normal-case ${inferred ? 'text-amber-300/80' : 'text-emerald-300/80'}`}>
          {inferred ? confidenceLabel(confidence) : 'measured'}
        </span>
      </h3>
      <dl className="space-y-0.5">
        {filled.map(([label, value]) => (
          <div key={label} className="flex gap-2 text-[11px]">
            <dt className="w-24 shrink-0 text-zinc-600">{label}</dt>
            <dd className="text-zinc-300">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/** PromptLens 1:1 reverse-engineered prompt for this shot. */
function PromptLensPanel({ lens }: { lens: unknown }) {
  const l = (lens || {}) as {
    core_prompt?: string
    deep_description?: string
    subject?: string
    environment?: string
    camera?: string
    lighting?: string
    style?: string
    mood?: string
    confidence?: number
  }
  if (!l.core_prompt && !l.deep_description) return null
  return (
    <section className="space-y-1.5 rounded border border-amber-500/30 bg-amber-500/5 p-2">
      <h3 className="text-[11px] uppercase tracking-wide text-amber-300 flex items-center gap-2">
        PromptLens 1:1 prompt
        {l.confidence ? (
          <span className="text-[9px] normal-case text-amber-300/80">{confidenceLabel(l.confidence)}</span>
        ) : null}
      </h3>
      {l.core_prompt ? (
        <p className="text-[12px] text-amber-100 leading-snug">
          <span className="text-amber-500/70">Core: </span>{l.core_prompt}
        </p>
      ) : null}
      {l.deep_description ? (
        <p className="text-[11px] text-zinc-300 leading-snug">{l.deep_description}</p>
      ) : null}
      {([['Subject', l.subject], ['Environment', l.environment], ['Camera', l.camera],
         ['Lighting', l.lighting], ['Style', l.style], ['Mood', l.mood]] as [string, string | undefined][])
        .filter(([, v]) => v)
        .map(([label, value]) => (
          <div key={label} className="flex gap-2 text-[11px]">
            <dt className="w-24 shrink-0 text-amber-500/70">{label}</dt>
            <dd className="text-zinc-300">{value}</dd>
          </div>
        ))}
    </section>
  )
}


function PromptEditor({
  shot,
  busy,
  onSave,
}: {
  shot: AnalyzedShot
  busy: boolean
  onSave: (prompts: Record<string, string>) => void
}) {
  const [video, setVideo] = useState(shot.prompts.video)
  const [negative, setNegative] = useState(shot.prompts.negative)
  useEffect(() => {
    setVideo(shot.prompts.video)
    setNegative(shot.prompts.negative)
  }, [shot.id, shot.prompts.video, shot.prompts.negative])

  const dirty = video !== shot.prompts.video || negative !== shot.prompts.negative
  return (
    <section className="space-y-1.5">
      <h3 className="text-[11px] uppercase tracking-wide text-zinc-500 flex items-center gap-2">
        Prompt
        {shot.prompts.edited && <span className="text-[9px] normal-case text-violet-300">edited by you</span>}
      </h3>
      <textarea
        value={video}
        onChange={e => setVideo(e.target.value)}
        rows={4}
        aria-label="Video generation prompt"
        placeholder="Analyse the shots to derive a prompt"
        className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-[11px] text-zinc-200"
      />
      <input
        value={negative}
        onChange={e => setNegative(e.target.value)}
        aria-label="Negative prompt"
        placeholder="Negative prompt"
        className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-[11px] text-zinc-200"
      />
      <button
        onClick={() => onSave({ video, negative })}
        disabled={busy || !dirty}
        className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-[11px] hover:bg-zinc-700 disabled:opacity-40"
      >
        <Wand2 className="h-3 w-3" /> Save prompt
      </button>
    </section>
  )
}
