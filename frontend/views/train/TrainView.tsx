import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Ban, FolderOpen, Images, Layers, Loader2, Play, Plus, RefreshCw, Sparkles, Trash2, Video, Wand2 } from 'lucide-react'
import { useProjects } from '../../contexts/ProjectContext'
import { jobsApi } from '../../lib/jobs-api'
import { logger } from '../../lib/logger'
import { datasetMediaUrl, trainingApi } from '../../lib/training-api'
import { videoAnalysisApi } from '../../lib/video-analysis-api'
import { filmOutputUrl } from '../../lib/film-api'
import { getBackendCredentials } from '../../lib/backend'
import { mediaResolver } from '../../lib/media-resolver'
import type { Job } from '../../types/jobs'
import { LORA_TARGETS, PRESET_LABEL, isRunActive, type Dataset, type DatasetPreset, type LoraEntry, type TrainingConfig, type TrainingRun, type TrainingStatusResponse } from '../../types/training'
import { LossSparkline } from './LossSparkline'

const selectClass = 'bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-violet-600'
const inputClass = selectClass + ' w-full'
const POLL_MS = 1500

type Panel = { kind: 'dataset'; id: string } | { kind: 'run'; id: string } | { kind: 'loras' } | { kind: 'empty' }

async function runMediaUrl(runId: string, path: string): Promise<string> {
  const standalone = mediaResolver()
  if (standalone) return standalone.output(path)
  const { url, token } = await getBackendCredentials()
  return `${url}/api/training/runs/${encodeURIComponent(runId)}/media?path=${encodeURIComponent(path)}&token=${encodeURIComponent(token)}`
}

function useUrl(resolve: () => Promise<string>, deps: unknown[]): string {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let cancelled = false
    resolve().then(u => { if (!cancelled) setUrl(u) }).catch(() => { if (!cancelled) setUrl('') })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return url
}

function DatasetThumb({ datasetId, file, alt }: { datasetId: string; file: string; alt: string }) {
  const url = useUrl(() => datasetMediaUrl(datasetId, file), [datasetId, file])
  return url ? <img src={url} alt={alt} className="w-full h-28 object-cover rounded bg-zinc-900" /> : <div className="w-full h-28 rounded bg-zinc-900" />
}

function SampleThumb({ runId, path, step }: { runId: string; path: string; step: number }) {
  const url = useUrl(() => runMediaUrl(runId, path), [runId, path])
  return (
    <figure className="m-0 w-28 shrink-0">
      {url ? <img src={url} alt={`Sample at step ${step}`} className="w-28 h-28 object-cover rounded bg-zinc-900" /> : <div className="w-28 h-28 rounded bg-zinc-900" />}
      <figcaption className="text-[10px] text-zinc-500 text-center">step {step}</figcaption>
    </figure>
  )
}

function HistoryThumb({ job }: { job: Job }) {
  const first = job.outputs[0]
  const url = useUrl(() => (first ? filmOutputUrl(first.thumb || first.path) : Promise.resolve('')), [first?.path])
  return url ? <img src={url} alt={job.title} className="w-10 h-10 object-cover rounded bg-zinc-900" /> : <div className="w-10 h-10 rounded bg-zinc-900" />
}

function formatEta(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return ''
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

/** The Train tab: build a dataset, train a LoRA within 12 GB, keep the registry. */
export function TrainView() {
  const { goHome, openHistory } = useProjects()
  const [status, setStatus] = useState<TrainingStatusResponse | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [runs, setRuns] = useState<TrainingRun[]>([])
  const [loras, setLoras] = useState<LoraEntry[]>([])
  const [panel, setPanel] = useState<Panel>({ kind: 'empty' })
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    const [s, d, r, l] = await Promise.all([trainingApi.status(), trainingApi.listDatasets(), trainingApi.listRuns(), trainingApi.listLoras()])
    setStatus(s); setDatasets(d); setRuns(r); setLoras(l)
  }, [])

  useEffect(() => { refresh().catch(e => setError(String(e))) }, [refresh])

  const anyActive = runs.some(isRunActive)
  useEffect(() => {
    if (!anyActive) return
    const timer = window.setInterval(() => { trainingApi.listRuns().then(setRuns).catch(e => logger.warn(`runs poll: ${String(e)}`)) }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [anyActive])
  useEffect(() => {
    // When a run finishes, the registry and status change too.
    if (!anyActive) refresh().catch(() => undefined)
  }, [anyActive, refresh])

  const createDataset = useCallback(async () => {
    try {
      const dataset = await trainingApi.createDataset({ name: `Dataset ${datasets.length + 1}`, preset: 'character', trigger: '' })
      await refresh()
      setPanel({ kind: 'dataset', id: dataset.id })
    } catch (e) { setError(String(e)) }
  }, [datasets.length, refresh])

  const selectedDataset = panel.kind === 'dataset' ? datasets.find(d => d.id === panel.id) ?? null : null
  const selectedRun = panel.kind === 'run' ? runs.find(r => r.id === panel.id) ?? null : null

  return (
    <div className="h-full flex flex-col bg-zinc-950 text-zinc-200">
      <header className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800">
        <button onClick={goHome} aria-label="Back to home" className="p-1 rounded hover:bg-zinc-800 text-zinc-400"><ArrowLeft className="h-4 w-4" /></button>
        <h1 className="text-sm font-semibold text-white flex items-center gap-2"><Layers className="h-4 w-4 text-fuchsia-300" /> Train</h1>
        <div className="flex items-center gap-1.5 flex-wrap ml-2" data-testid="trainer-status">
          {status?.trainers.map(t => (
            <span key={t.id} title={t.reason || t.notes} className={`text-[10px] px-1.5 py-0.5 rounded border ${t.installed ? 'border-emerald-800 text-emerald-300' : t.fits_12gb ? 'border-zinc-700 text-zinc-400' : 'border-amber-900 text-amber-400'}`}>
              {t.name} · {t.installed ? 'ready' : t.fits_12gb ? 'not installed' : 'needs more than 12 GB'}
            </span>
          ))}
          {status && <span className="text-[10px] text-zinc-500">{Math.round(status.machine_vram_mb / 1024)} GB card</span>}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {error && <span className="text-[11px] text-red-300 max-w-md truncate" title={error}>{error}</span>}
          <button onClick={() => refresh().catch(e => setError(String(e)))} aria-label="Refresh" className="p-1 rounded hover:bg-zinc-800 text-zinc-400"><RefreshCw className="h-3.5 w-3.5" /></button>
        </div>
      </header>
      <div className="flex-1 min-h-0 flex">
        <aside className="w-64 shrink-0 border-r border-zinc-800 overflow-y-auto p-2 space-y-4">
          <section>
            <div className="flex items-center justify-between px-2 mb-1">
              <h2 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Datasets</h2>
              <button onClick={() => void createDataset()} className="text-[11px] text-fuchsia-300 hover:text-fuchsia-200 flex items-center gap-0.5"><Plus className="h-3 w-3" /> New</button>
            </div>
            {datasets.length === 0 && <p className="px-2 text-xs text-zinc-600">Start with a dataset: a folder, a video, or images from History.</p>}
            {datasets.map(d => (
              <button key={d.id} onClick={() => setPanel({ kind: 'dataset', id: d.id })} className={`w-full text-left px-2 py-1.5 rounded text-xs hover:bg-zinc-800 ${panel.kind === 'dataset' && panel.id === d.id ? 'bg-zinc-800 text-white' : 'text-zinc-300'}`} data-testid="dataset-item">
                <div className="truncate">{d.name || 'Untitled'}</div>
                <div className="text-[10px] text-zinc-500">{PRESET_LABEL[d.preset]} · {d.items.length} images{d.trigger ? ` · ${d.trigger}` : ''}</div>
              </button>
            ))}
          </section>
          <section>
            <h2 className="px-2 mb-1 text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Training runs</h2>
            {runs.length === 0 && <p className="px-2 text-xs text-zinc-600">No runs yet.</p>}
            {runs.map(r => (
              <button key={r.id} onClick={() => setPanel({ kind: 'run', id: r.id })} className={`w-full text-left px-2 py-1.5 rounded text-xs hover:bg-zinc-800 ${panel.kind === 'run' && panel.id === r.id ? 'bg-zinc-800 text-white' : 'text-zinc-300'}`} data-testid="run-item">
                <div className="truncate">{r.name}</div>
                <div className="text-[10px] text-zinc-500">{r.status}{isRunActive(r) ? ` · ${r.step}/${r.total_steps}` : ''} · {r.config.target}</div>
              </button>
            ))}
          </section>
          <section>
            <button onClick={() => setPanel({ kind: 'loras' })} className={`w-full text-left px-2 py-1.5 rounded text-xs hover:bg-zinc-800 ${panel.kind === 'loras' ? 'bg-zinc-800 text-white' : 'text-zinc-300'}`}>
              <div className="flex items-center gap-1"><Layers className="h-3 w-3" /> LoRA registry</div>
              <div className="text-[10px] text-zinc-500">{loras.length} LoRA{loras.length === 1 ? '' : 's'}</div>
            </button>
          </section>
        </aside>
        <main className="flex-1 min-w-0 overflow-y-auto p-4">
          {panel.kind === 'empty' && (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto">
              <Layers className="h-8 w-8 text-zinc-800 mb-2" />
              <p className="text-sm text-zinc-300">Teach the image model a character, a style or an object.</p>
              <p className="text-xs text-zinc-500 mt-1">Build a dataset (a folder, video frames or your own History outputs), let Florence caption it with your trigger word, and train a LoRA that fits this 12 GB card. Video LoRAs (Wan 2.2, LTX-2) need bigger cards and are refused here rather than crashing.</p>
              <button onClick={() => void createDataset()} className="mt-4 btn-chip bg-fuchsia-700 hover:bg-fuchsia-600 text-white"><Plus className="h-3.5 w-3.5" /> New dataset</button>
            </div>
          )}
          {selectedDataset && <DatasetBuilder key={selectedDataset.id} dataset={selectedDataset} status={status} onChanged={refresh} onStarted={run => { refresh().then(() => setPanel({ kind: 'run', id: run.id })).catch(() => setPanel({ kind: 'run', id: run.id })) }} onDeleted={() => { setPanel({ kind: 'empty' }); void refresh() }} onError={setError} />}
          {selectedRun && <RunDetail run={selectedRun} dataset={datasets.find(d => d.id === selectedRun.dataset_id) ?? null} onChanged={refresh} onDeleted={() => { setPanel({ kind: 'empty' }); void refresh() }} onResumed={run => setPanel({ kind: 'run', id: run.id })} onOpenHistory={openHistory} onError={setError} />}
          {panel.kind === 'loras' && <Registry loras={loras} onChanged={refresh} onError={setError} />}
        </main>
      </div>
    </div>
  )
}

// ---- dataset builder ------------------------------------------------------------------------

function DatasetBuilder({ dataset, status, onChanged, onStarted, onDeleted, onError }: { dataset: Dataset; status: TrainingStatusResponse | null; onChanged: () => Promise<void>; onStarted: (run: TrainingRun) => void; onDeleted: () => void; onError: (message: string) => void }) {
  const [busy, setBusy] = useState('')
  const [meta, setMeta] = useState({ name: dataset.name, preset: dataset.preset, trigger: dataset.trigger })
  const [target, setTarget] = useState('z_image')
  const [config, setConfig] = useState<TrainingConfig | null>(null)
  const [runName, setRunName] = useState('')
  const [historyJobs, setHistoryJobs] = useState<Job[] | null>(null)
  const [analyses, setAnalyses] = useState<{ id: string; title: string }[] | null>(null)
  const [videoFps, setVideoFps] = useState(1)

  useEffect(() => { setMeta({ name: dataset.name, preset: dataset.preset, trigger: dataset.trigger }) }, [dataset.id, dataset.name, dataset.preset, dataset.trigger])

  const run = useCallback(async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label)
    try { await fn(); await onChanged() } catch (e) { onError(String(e)) } finally { setBusy('') }
  }, [onChanged, onError])

  const saveMeta = useCallback(() => {
    if (meta.name === dataset.name && meta.preset === dataset.preset && meta.trigger === dataset.trigger) return
    void run('Saving', () => trainingApi.updateDataset(dataset.id, meta))
  }, [dataset, meta, run])

  useEffect(() => {
    if (dataset.items.length === 0) { setConfig(null); return }
    let cancelled = false
    trainingApi.suggest(dataset.id, target).then(c => { if (!cancelled) setConfig(c) }).catch(e => onError(String(e)))
    return () => { cancelled = true }
  }, [dataset.id, dataset.items.length, dataset.preset, target, onError])

  const addFolder = () => run('Importing', async () => {
    const folder = await window.electronAPI.showOpenDirectoryDialog({ title: 'Choose an image folder' })
    if (folder) await trainingApi.importItems(dataset.id, { folder })
  })
  const addImages = () => run('Importing', async () => {
    const paths = await window.electronAPI.showOpenFileDialog({ title: 'Choose images', filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'webp'] }], properties: ['openFile', 'multiSelections'] })
    if (paths?.length) await trainingApi.importItems(dataset.id, { image_paths: paths })
  })
  const addVideo = () => run('Importing', async () => {
    const paths = await window.electronAPI.showOpenFileDialog({ title: 'Choose a video', filters: [{ name: 'Video', extensions: ['mp4', 'mov', 'mkv', 'webm'] }], properties: ['openFile'] })
    if (paths?.[0]) await trainingApi.importItems(dataset.id, { video_path: paths[0], video_fps: videoFps, video_max_frames: 48 })
  })
  const loadHistory = () => run('Loading', async () => {
    const { jobs } = await jobsApi.list({ kind: 'image_gen', status: 'complete', limit: 40 })
    setHistoryJobs(jobs.filter(j => j.outputs.some(o => o.kind === 'image')))
    setAnalyses((await videoAnalysisApi.list()).map(a => ({ id: a.id, title: a.title })))
  })
  const fromJob = (job: Job) => run('Importing', () => trainingApi.importItems(dataset.id, { job_ids: [job.id] }))
  const fromAnalysis = (id: string) => run('Importing', () => trainingApi.importItems(dataset.id, { analysis_id: id }))

  const machine = status?.machine_vram_mb ?? 12288
  const fits = config ? config.estimated_vram_mb <= machine : true
  const trainer = status?.trainers.find(t => t.id === config?.trainer)
  const canTrain = dataset.items.length >= 4 && config !== null && fits && (trainer?.installed ?? false)
  const blocker = dataset.items.length < 4 ? 'Add at least 4 images (12 or more is the sweet spot).' : !fits ? `Estimated ${(config!.estimated_vram_mb / 1024).toFixed(1)} GB does not fit this ${Math.round(machine / 1024)} GB card.` : trainer && !trainer.installed ? trainer.reason : ''

  return (
    <div className="max-w-5xl space-y-4" data-testid="dataset-builder">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        <label className="block"><span className="text-[10px] text-zinc-500 uppercase tracking-wide">Name</span><input className={inputClass} value={meta.name} onChange={e => setMeta(m => ({ ...m, name: e.target.value }))} onBlur={saveMeta} aria-label="Dataset name" /></label>
        <label className="block"><span className="text-[10px] text-zinc-500 uppercase tracking-wide">Preset</span>
          <select className={inputClass} value={meta.preset} onChange={e => { const preset = e.target.value as DatasetPreset; setMeta(m => ({ ...m, preset })); void run('Saving', () => trainingApi.updateDataset(dataset.id, { preset })) }} aria-label="Dataset preset">
            {(Object.keys(PRESET_LABEL) as DatasetPreset[]).map(p => <option key={p} value={p}>{PRESET_LABEL[p]}</option>)}
          </select></label>
        <label className="block"><span className="text-[10px] text-zinc-500 uppercase tracking-wide">Trigger word</span><input className={inputClass} value={meta.trigger} placeholder="e.g. mara_v1" onChange={e => setMeta(m => ({ ...m, trigger: e.target.value }))} onBlur={saveMeta} aria-label="Trigger word" /></label>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        <button onClick={() => void addFolder()} disabled={!!busy} className="btn-chip"><FolderOpen className="h-3.5 w-3.5" /> Add folder</button>
        <button onClick={() => void addImages()} disabled={!!busy} className="btn-chip"><Images className="h-3.5 w-3.5" /> Add images</button>
        <button onClick={() => void addVideo()} disabled={!!busy} className="btn-chip"><Video className="h-3.5 w-3.5" /> Add video frames</button>
        <label className="text-[10px] text-zinc-500 flex items-center gap-1">at <input type="number" min="0.1" step="0.5" value={videoFps} onChange={e => setVideoFps(Number(e.target.value) || 1)} className={selectClass + ' w-14'} aria-label="Frames per second" /> fps</label>
        <button onClick={() => void loadHistory()} disabled={!!busy} className="btn-chip"><Sparkles className="h-3.5 w-3.5" /> From History</button>
        <button onClick={() => void run('Captioning', () => trainingApi.caption(dataset.id))} disabled={!!busy || dataset.items.length === 0} className="btn-chip bg-violet-800/70 hover:bg-violet-700 text-violet-100"><Wand2 className="h-3.5 w-3.5" /> Auto-caption</button>
        <span className="ml-auto text-[11px] text-zinc-500">{busy ? <span className="flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> {busy}…</span> : `${dataset.items.length} images${dataset.caption_model ? ` · captioned by ${dataset.caption_model}` : ''}`}</span>
        <button onClick={() => { if (window.confirm('Delete this dataset and its images?')) void trainingApi.deleteDataset(dataset.id).then(onDeleted).catch(e => onError(String(e))) }} aria-label="Delete dataset" className="p-1 text-zinc-600 hover:text-red-300"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      {historyJobs && (
        <section className="rounded border border-zinc-800 p-2 space-y-1" data-testid="history-picker">
          <div className="flex items-center justify-between"><span className="text-[10px] text-zinc-500 uppercase tracking-wide">Recent image outputs</span><button onClick={() => { setHistoryJobs(null); setAnalyses(null) }} className="text-[10px] text-zinc-500 hover:text-zinc-300">close</button></div>
          {historyJobs.length === 0 && <p className="text-xs text-zinc-600">No finished image jobs in History yet.</p>}
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-1">
            {historyJobs.map(job => (
              <button key={job.id} onClick={() => void fromJob(job)} disabled={!!busy} className="flex items-center gap-2 text-left text-xs px-1.5 py-1 rounded hover:bg-zinc-800">
                <HistoryThumb job={job} /><span className="truncate flex-1">{job.title}</span><Plus className="h-3 w-3 text-zinc-500" />
              </button>
            ))}
          </div>
          {analyses && analyses.length > 0 && (
            <>
              <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Analysed videos (all frames)</span>
              <div className="flex flex-wrap gap-1">{analyses.map(a => <button key={a.id} onClick={() => void fromAnalysis(a.id)} disabled={!!busy} className="btn-chip">{a.title || a.id}</button>)}</div>
            </>
          )}
        </section>
      )}
      {dataset.items.length > 0 && (
        <section>
          <h2 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold mb-1">Review captions</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2" data-testid="dataset-grid">
            {dataset.items.map(item => <ItemCard key={item.id} datasetId={dataset.id} item={item} disabled={!!busy} onSave={caption => run('Saving', () => trainingApi.updateItem(dataset.id, item.id, caption))} onRemove={() => run('Removing', () => trainingApi.removeItem(dataset.id, item.id))} />)}
          </div>
        </section>
      )}
      <section className="rounded border border-zinc-800 p-3 space-y-2" data-testid="train-panel">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Train a LoRA</h2>
          <label className="text-[11px] text-zinc-400 flex items-center gap-1">Target
            <select className={selectClass} value={target} onChange={e => setTarget(e.target.value)} aria-label="Training target">
              {LORA_TARGETS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </label>
          <input className={selectClass + ' w-56'} placeholder={`${dataset.name || 'Dataset'} · ${target}`} value={runName} onChange={e => setRunName(e.target.value)} aria-label="Run name" />
        </div>
        {config && (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 text-[11px]">
            {([['rank', 'Rank'], ['steps', 'Steps'], ['learning_rate', 'LR'], ['resolution', 'Resolution'], ['blocks_to_swap', 'Block swap'], ['save_every', 'Save every'], ['sample_every', 'Sample every']] as const).map(([key, label]) => (
              <label key={key} className="block"><span className="text-[10px] text-zinc-500 uppercase tracking-wide">{label}</span>
                <input type="number" step={key === 'learning_rate' ? '0.00001' : '1'} className={inputClass} value={config[key]} onChange={e => setConfig(c => (c ? { ...c, [key]: Number(e.target.value) } : c))} aria-label={label} /></label>
            ))}
            <label className="flex items-center gap-1 text-zinc-400 self-end"><input type="checkbox" checked={config.fp8} onChange={e => setConfig(c => (c ? { ...c, fp8: e.target.checked } : c))} /> fp8</label>
            <div className="col-span-2 md:col-span-4 lg:col-span-7 text-[11px] text-zinc-500">
              {config.trainer} · estimated <span className={fits ? 'text-emerald-300' : 'text-amber-300'}>{(config.estimated_vram_mb / 1024).toFixed(1)} GB</span> of {Math.round(machine / 1024)} GB · buckets {config.buckets.join('/')}
            </div>
          </div>
        )}
        <div className="flex items-center gap-2">
          <button onClick={() => run('Starting', async () => { const started = await trainingApi.start({ dataset_id: dataset.id, name: runName, config }); onStarted(started) })} disabled={!canTrain || !!busy} className="btn-chip bg-fuchsia-700 hover:bg-fuchsia-600 text-white disabled:opacity-40" data-testid="start-training"><Play className="h-3.5 w-3.5" /> Start training</button>
          {blocker && <span className="text-[11px] text-amber-300" data-testid="train-blocker">{blocker}</span>}
        </div>
      </section>
    </div>
  )
}

function ItemCard({ datasetId, item, disabled, onSave, onRemove }: { datasetId: string; item: Dataset['items'][number]; disabled: boolean; onSave: (caption: string) => void; onRemove: () => void }) {
  const [caption, setCaption] = useState(item.caption)
  useEffect(() => setCaption(item.caption), [item.caption])
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-1.5 space-y-1" data-testid="dataset-item-card">
      <div className="relative">
        <DatasetThumb datasetId={datasetId} file={item.file} alt={item.caption || item.file} />
        <span className="absolute top-1 left-1 text-[9px] px-1 rounded bg-black/60 text-zinc-300">{item.source}{item.edited ? ' · edited' : ''}</span>
        <button onClick={onRemove} disabled={disabled} aria-label={`Remove ${item.file}`} className="absolute top-1 right-1 p-0.5 rounded bg-black/60 text-zinc-400 hover:text-red-300"><Trash2 className="h-3 w-3" /></button>
      </div>
      <textarea value={caption} onChange={e => setCaption(e.target.value)} onBlur={() => { if (caption !== item.caption) onSave(caption) }} rows={2} placeholder="Caption (auto-caption fills this)" aria-label={`Caption for ${item.file}`} className="w-full bg-zinc-950 border border-zinc-800 rounded px-1.5 py-1 text-[11px] text-zinc-300 resize-none focus:outline-none focus:border-violet-600" />
    </div>
  )
}

// ---- run detail -----------------------------------------------------------------------------

function RunDetail({ run, dataset, onChanged, onDeleted, onResumed, onOpenHistory, onError }: { run: TrainingRun; dataset: Dataset | null; onChanged: () => Promise<void>; onDeleted: () => void; onResumed: (run: TrainingRun) => void; onOpenHistory: () => void; onError: (message: string) => void }) {
  const active = isRunActive(run)
  const pct = run.total_steps ? Math.round((100 * run.step) / run.total_steps) : 0
  const canResume = !active && run.checkpoints.length > 0 && run.status !== 'complete'
  const samples = useMemo(() => run.samples.slice(-8), [run.samples])
  return (
    <div className="max-w-4xl space-y-4" data-testid="run-detail">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="text-sm font-semibold text-white">{run.name}</h2>
        <span className={`text-xs ${run.status === 'failed' ? 'text-red-300' : active ? 'text-fuchsia-300' : run.status === 'complete' ? 'text-emerald-300' : 'text-zinc-400'}`} data-testid="run-status">{run.status}{run.phase && run.phase !== run.status ? ` · ${run.phase}` : ''}</span>
        <span className="text-[11px] text-zinc-500">{run.config.target} · {run.config.trainer} · rank {run.config.rank} · {dataset ? `${dataset.items.length} images` : ''}{run.trigger ? ` · trigger “${run.trigger}”` : ''}</span>
        <div className="ml-auto flex gap-1.5">
          {active && <button onClick={() => trainingApi.cancel(run.id).then(() => onChanged()).catch(e => onError(String(e)))} className="btn-chip text-red-300"><Ban className="h-3.5 w-3.5" /> Cancel</button>}
          {canResume && <button onClick={() => trainingApi.start({ dataset_id: run.dataset_id, resume_run_id: run.id, name: `${run.name} (resumed)` }).then(r => { onResumed(r); return onChanged() }).catch(e => onError(String(e)))} className="btn-chip"><Play className="h-3.5 w-3.5" /> Resume from step {run.checkpoints.length ? run.checkpoints[run.checkpoints.length - 1].match(/-(\d+)\.safetensors$/)?.[1]?.replace(/^0+/, '') ?? '' : ''}</button>}
          {run.job_id && <button onClick={onOpenHistory} className="btn-chip">Open in History</button>}
          {!active && <button onClick={() => { if (window.confirm('Delete this run? Its LoRA stays in the registry.')) void trainingApi.deleteRun(run.id).then(onDeleted).catch(e => onError(String(e))) }} aria-label="Delete run" className="p-1 text-zinc-600 hover:text-red-300"><Trash2 className="h-3.5 w-3.5" /></button>}
        </div>
      </div>
      <div className="h-1.5 rounded bg-zinc-800 overflow-hidden" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Training progress">
        <div className={`h-full transition-all ${run.status === 'failed' ? 'bg-red-500' : 'bg-fuchsia-500'}`} style={{ width: `${Math.max(active ? 2 : 0, pct)}%` }} />
      </div>
      <div className="flex items-center gap-4 text-[11px] text-zinc-400 flex-wrap">
        <span data-testid="run-step">step {run.step}/{run.total_steps}</span>
        {active && run.eta_seconds !== null && <span>ETA {formatEta(run.eta_seconds)}</span>}
        {run.peak_vram_mb !== null && <span>peak {(run.peak_vram_mb / 1024).toFixed(1)} GB</span>}
        {run.loss_history.length > 0 && <span>loss {run.loss_history[run.loss_history.length - 1].toFixed(4)}</span>}
        {run.error && <span className="text-red-300">{run.error}</span>}
      </div>
      <LossSparkline values={run.loss_history} width={480} height={72} />
      {samples.length > 0 && (
        <section>
          <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold mb-1">Samples</h3>
          <div className="flex gap-2 overflow-x-auto pb-1" data-testid="sample-grid">{samples.map(s => <SampleThumb key={s.path} runId={run.id} path={s.path} step={s.step} />)}</div>
        </section>
      )}
      {run.status === 'complete' && run.lora_path && (
        <p className="text-xs text-emerald-300">LoRA saved to the registry: <code className="text-zinc-300">{run.lora_path}</code>. It now shows in the LoRA pickers for {run.config.target}.</p>
      )}
      {run.checkpoints.length > 0 && <p className="text-[11px] text-zinc-500">{run.checkpoints.length} checkpoint{run.checkpoints.length === 1 ? '' : 's'} kept for resume.</p>}
      {run.log_tail && <details className="text-[11px]"><summary className="text-zinc-500 cursor-pointer">Trainer log</summary><pre className="mt-1 max-h-48 overflow-auto bg-zinc-900 rounded p-2 text-zinc-400 whitespace-pre-wrap">{run.log_tail}</pre></details>}
    </div>
  )
}

// ---- registry -------------------------------------------------------------------------------

function Registry({ loras, onChanged, onError }: { loras: LoraEntry[]; onChanged: () => Promise<void>; onError: (message: string) => void }) {
  const [target, setTarget] = useState('z_image')
  const [busy, setBusy] = useState(false)
  const importLora = async () => {
    setBusy(true)
    try {
      const paths = await window.electronAPI.showOpenFileDialog({ title: 'Choose a LoRA (.safetensors)', filters: [{ name: 'LoRA', extensions: ['safetensors'] }], properties: ['openFile'] })
      if (paths?.[0]) { await trainingApi.importLora({ path: paths[0], target }); await onChanged() }
    } catch (e) { onError(String(e)) } finally { setBusy(false) }
  }
  return (
    <div className="max-w-4xl space-y-3" data-testid="lora-registry">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="text-sm font-semibold text-white">LoRA registry</h2>
        <span className="text-[11px] text-zinc-500">Trained here or imported. Each knows its base model and trigger, so pickers only offer what fits.</span>
        <div className="ml-auto flex items-center gap-1.5">
          <select className={selectClass} value={target} onChange={e => setTarget(e.target.value)} aria-label="Import target">{LORA_TARGETS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}</select>
          <button onClick={() => void importLora()} disabled={busy} className="btn-chip"><Plus className="h-3.5 w-3.5" /> Import .safetensors</button>
        </div>
      </div>
      <DownloadFromUrl target={target} onChanged={onChanged} />
      {loras.length === 0 && <p className="text-xs text-zinc-600">Nothing yet. Finish a training run, import a file, or paste a link above.</p>}
      <div className="space-y-1">
        {loras.map(entry => <LoraRow key={entry.id} entry={entry} onChanged={onChanged} onError={onError} />)}
      </div>
    </div>
  )
}

/** Paste a Hugging Face / Civitai / direct .safetensors link; the backend
 *  downloads it as a History job and registers it for the chosen target. */
function DownloadFromUrl({ target, onChanged }: { target: string; onChanged: () => Promise<void> }) {
  const [url, setUrl] = useState('')
  const [trigger, setTrigger] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const running = job !== null && (job.status === 'queued' || job.status === 'running')
  const jobId = running && job ? job.id : ''

  useEffect(() => {
    if (!jobId) return
    const timer = window.setInterval(() => {
      jobsApi.get(jobId).then(({ job: fresh }) => {
        setJob(fresh)
        if (fresh.status === 'complete') { setUrl(''); setTrigger(''); setApiKey(''); void onChanged() }
      }).catch(() => undefined)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [jobId, onChanged])

  const start = async () => {
    setError('')
    setJob(null)
    try {
      const { job_id } = await trainingApi.downloadLora({ url: url.trim(), target, trigger: trigger.trim(), api_key: apiKey })
      const { job: fresh } = await jobsApi.get(job_id)
      setJob(fresh)
      if (fresh.status === 'complete') { setUrl(''); setTrigger(''); setApiKey(''); void onChanged() }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-2 space-y-1.5" data-testid="lora-url-panel">
      <div className="flex items-center gap-2 flex-wrap">
        <input className={selectClass + ' flex-1 min-w-64'} placeholder="Paste a Hugging Face or Civitai link, or a direct .safetensors URL" value={url} onChange={e => setUrl(e.target.value)} aria-label="LoRA link" data-testid="lora-url-input" disabled={running} />
        <input className={selectClass + ' w-28'} placeholder="trigger word" value={trigger} onChange={e => setTrigger(e.target.value)} aria-label="Trigger for the downloaded LoRA" disabled={running} />
        <input type="password" className={selectClass + ' w-44'} placeholder="API key (used once, not saved)" value={apiKey} onChange={e => setApiKey(e.target.value)} aria-label="API key, used once and never saved" disabled={running} />
        <button onClick={() => void start()} disabled={running || !url.trim()} className="btn-chip" data-testid="lora-url-download">
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} Download
        </button>
      </div>
      <p className="text-[10px] text-zinc-600">Downloads into the {target} LoRA folder and registers it. Gated files may need your Civitai or Hugging Face key — it is sent once with this request and never stored.</p>
      {running && job && <p className="text-[11px] text-violet-300" data-testid="lora-url-status">{job.phase || 'starting'}{job.progress > 0 ? ` · ${job.progress}%` : ''}</p>}
      {job?.status === 'failed' && <p className="text-[11px] text-red-300" data-testid="lora-url-status">{job.error || 'Download failed'}</p>}
      {job?.status === 'cancelled' && <p className="text-[11px] text-zinc-500" data-testid="lora-url-status">Download cancelled.</p>}
      {job?.status === 'complete' && <p className="text-[11px] text-emerald-300" data-testid="lora-url-status">Added to the registry.</p>}
      {error && <p className="text-[11px] text-red-300" data-testid="lora-url-status">{error}</p>}
    </div>
  )
}

function LoraRow({ entry, onChanged, onError }: { entry: LoraEntry; onChanged: () => Promise<void>; onError: (message: string) => void }) {
  const [draft, setDraft] = useState({ name: entry.name, trigger: entry.trigger, default_multiplier: entry.default_multiplier })
  useEffect(() => setDraft({ name: entry.name, trigger: entry.trigger, default_multiplier: entry.default_multiplier }), [entry])
  const save = () => {
    if (draft.name === entry.name && draft.trigger === entry.trigger && draft.default_multiplier === entry.default_multiplier) return
    trainingApi.updateLora(entry.id, draft).then(() => onChanged()).catch(e => onError(String(e)))
  }
  return (
    <div className="grid grid-cols-[1fr_auto_auto_auto_auto] items-center gap-2 rounded border border-zinc-800 px-2 py-1.5 text-xs" data-testid="lora-row">
      <div className="min-w-0">
        <input className="bg-transparent text-zinc-100 w-full focus:outline-none border-b border-transparent focus:border-violet-600" value={draft.name} onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} onBlur={save} aria-label={`Name of ${entry.name}`} />
        <div className="text-[10px] text-zinc-500 truncate" title={entry.file}>{entry.target}{entry.imported ? ' · imported' : entry.run_id ? ' · trained here' : ''} · {(entry.size_bytes / 1_048_576).toFixed(1)} MB</div>
      </div>
      <label className="text-[10px] text-zinc-500">trigger <input className={selectClass + ' w-28'} value={draft.trigger} onChange={e => setDraft(d => ({ ...d, trigger: e.target.value }))} onBlur={save} aria-label={`Trigger for ${entry.name}`} /></label>
      <label className="text-[10px] text-zinc-500">strength <input type="number" step="0.05" min="0" max="2" className={selectClass + ' w-16'} value={draft.default_multiplier} onChange={e => setDraft(d => ({ ...d, default_multiplier: Number(e.target.value) }))} onBlur={save} aria-label={`Default strength for ${entry.name}`} /></label>
      <span className="text-[10px] text-zinc-600">{new Date(entry.created_at).toLocaleDateString()}</span>
      <button onClick={() => { if (window.confirm(`Delete ${entry.name}? The file is removed from the LoRA folder.`)) void trainingApi.deleteLora(entry.id).then(() => onChanged()).catch(e => onError(String(e))) }} aria-label={`Delete ${entry.name}`} className="p-1 text-zinc-600 hover:text-red-300"><Trash2 className="h-3.5 w-3.5" /></button>
    </div>
  )
}
