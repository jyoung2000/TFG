import { useCallback, useEffect, useState } from 'react'
import { Copy, ExternalLink, FolderOpen, GitBranch, Play, RefreshCw, Trash2, X, XCircle } from 'lucide-react'
import { Lightbox, type LightboxItem } from '../../components/Lightbox'
import { filmOutputUrl } from '../../lib/film-api'
import { jobsApi } from '../../lib/jobs-api'
import { logger } from '../../lib/logger'
import { JOB_KIND_LABEL, isActive, type Job } from '../../types/jobs'
import { formatSeconds, formatWhen, statusTone } from './JobCard'
import { LossSparkline } from '../train/LossSparkline'

interface JobDrawerProps {
  jobId: string
  onClose: () => void
  onSelect: (jobId: string) => void
  onOpenReproduce: (job: Job) => void
  onOpenProject: (job: Job) => void
  onOpenQuick: (job: Job) => void
  onDeleted: (jobId: string) => void
}

type Loaded = { job: Job; lineage: Job[]; children: Job[] }

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">{title}</h3>
      {children}
    </section>
  )
}

function KeyValue({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined && v !== '')
  if (!entries.length) return <p className="text-xs text-zinc-600">none</p>
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-zinc-500">{key}</dt>
          <dd className="text-zinc-300 break-all">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

export function JobDrawer({ jobId, onClose, onSelect, onOpenReproduce, onOpenProject, onOpenQuick, onDeleted }: JobDrawerProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [items, setItems] = useState<LightboxItem[]>([])
  const [lightbox, setLightbox] = useState<number | null>(null)
  const [note, setNote] = useState('')

  const load = useCallback(async () => {
    try {
      const detail = await jobsApi.get(jobId)
      setLoaded(detail)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [jobId])

  useEffect(() => { void load() }, [load])

  // Keep an active job's details fresh without a second feed.
  useEffect(() => {
    if (!loaded || !isActive(loaded.job)) return
    const id = window.setInterval(() => void load(), 1500)
    return () => window.clearInterval(id)
  }, [loaded, load])

  useEffect(() => {
    let cancelled = false
    const outputs = loaded?.job.outputs ?? []
    void Promise.all(
      outputs
        .filter(o => o.kind !== 'file')
        .map(async (o): Promise<LightboxItem | null> => {
          try {
            return { url: await filmOutputUrl(o.path), kind: o.kind === 'video' ? 'video' : 'image', label: o.path.split(/[\\/]/).pop() ?? o.path, caption: loaded?.job.prompt }
          } catch {
            return null
          }
        }),
    ).then(resolved => { if (!cancelled) setItems(resolved.filter((x): x is LightboxItem => x !== null)) })
    return () => { cancelled = true }
  }, [loaded])

  const act = async (label: string, work: () => Promise<unknown>) => {
    setBusy(label)
    setNote('')
    try {
      await work()
      await load()
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const copyPrompt = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setNote('Prompt copied')
    } catch (err) {
      logger.warn(`Clipboard unavailable: ${err}`)
      setNote('Clipboard unavailable')
    }
  }

  const reveal = async (path: string) => {
    try {
      await window.electronAPI.showItemInFolder(path)
    } catch (err) {
      setNote(`Could not reveal file: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  const job = loaded?.job
  const canRerun = job ? (job.kind === 'video_gen' || job.kind === 'image_gen') && !isActive(job) : false
  const analysisId = typeof job?.inputs.analysis_id === 'string' ? job.inputs.analysis_id : ''

  return (
    <aside
      className="w-[26rem] shrink-0 border-l border-zinc-800 bg-zinc-950 overflow-y-auto"
      role="complementary"
      aria-label="Job details"
      data-testid="job-drawer"
    >
      <div className="sticky top-0 z-10 flex items-center justify-between px-4 py-3 border-b border-zinc-800 bg-zinc-950/95 backdrop-blur">
        <h2 className="text-sm font-semibold text-white truncate pr-2">{job ? (job.title || JOB_KIND_LABEL[job.kind]) : 'Job'}</h2>
        <button onClick={onClose} aria-label="Close job details" className="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-white">
          <X className="h-4 w-4" />
        </button>
      </div>

      {error && <p className="m-4 text-xs text-red-300">{error}</p>}
      {!job && !error && <p className="m-4 text-xs text-zinc-500">Loading…</p>}

      {job && (
        <div className="p-4 space-y-5">
          <div className="text-xs text-zinc-400 flex flex-wrap gap-x-3 gap-y-1">
            <span className={statusTone(job)}>{job.status}{isActive(job) ? ` · ${Math.round(job.progress)}% ${job.phase}` : ''}</span>
            <span>{JOB_KIND_LABEL[job.kind]}</span>
            {job.model && <span>{job.model}</span>}
            {job.provider && <span>{job.provider}</span>}
            <span>{formatWhen(job.created_at)}</span>
          </div>
          {job.error && <p className="text-xs text-red-300 bg-red-950/30 border border-red-900/50 rounded p-2 break-words">{job.error}</p>}

          {items.length > 0 && (
            <Section title={`Outputs (${job.outputs.length})`}>
              <div className="grid grid-cols-3 gap-1.5">
                {items.map((item, index) => (
                  <button
                    key={item.url}
                    onClick={() => setLightbox(index)}
                    className="aspect-video rounded overflow-hidden border border-zinc-800 bg-black relative cursor-zoom-in"
                    aria-label={`Open output ${index + 1}`}
                  >
                    {item.kind === 'video' ? (
                      <>
                        <video src={item.url} muted preload="metadata" className="w-full h-full object-cover" />
                        <Play className="absolute inset-0 m-auto h-5 w-5 text-white/80" />
                      </>
                    ) : (
                      <img src={item.url} alt={item.label ?? ''} loading="lazy" className="w-full h-full object-cover" />
                    )}
                  </button>
                ))}
              </div>
            </Section>
          )}

          <Section title="Actions">
            <div className="flex flex-wrap gap-1.5">
              {isActive(job) && (
                <button onClick={() => void act('cancel', () => jobsApi.cancel(job.id))} disabled={!!busy} className="btn-chip text-red-300"><XCircle className="h-3.5 w-3.5" /> Cancel</button>
              )}
              {canRerun && (
                <button onClick={() => void act('rerun', () => jobsApi.rerun(job.id))} disabled={!!busy} className="btn-chip"><RefreshCw className="h-3.5 w-3.5" /> Re-run (same seed)</button>
              )}
              {job.prompt && (
                <button onClick={() => void copyPrompt(job.prompt)} className="btn-chip"><Copy className="h-3.5 w-3.5" /> Copy prompt</button>
              )}
              {(analysisId || job.kind === 'image_reproduce' || job.kind === 'video_reproduce' || job.kind === 'analysis') && (
                <button onClick={() => onOpenReproduce(job)} className="btn-chip"><ExternalLink className="h-3.5 w-3.5" /> Open in Reproduce</button>
              )}
              {job.project_id && (
                <button onClick={() => onOpenProject(job)} className="btn-chip"><ExternalLink className="h-3.5 w-3.5" /> Open in Storyboard</button>
              )}
              {job.kind === 'video_gen' && !job.project_id && job.prompt && (
                <button onClick={() => onOpenQuick(job)} className="btn-chip"><ExternalLink className="h-3.5 w-3.5" /> Open in Quick</button>
              )}
              {job.outputs[0]?.path && (
                <button onClick={() => void reveal(job.outputs[0].path)} className="btn-chip"><FolderOpen className="h-3.5 w-3.5" /> Reveal in folder</button>
              )}
              {!isActive(job) && !confirmDelete && (
                <button onClick={() => setConfirmDelete(true)} className="btn-chip text-red-300"><Trash2 className="h-3.5 w-3.5" /> Delete</button>
              )}
            </div>
            {confirmDelete && (
              <div className="mt-2 rounded border border-red-900/60 bg-red-950/30 p-2 text-xs space-y-2" role="alertdialog" aria-label="Confirm delete">
                <p className="text-red-200">Delete this job from History?{job.outputs.length ? ' You can also delete its files on disk.' : ''}</p>
                <div className="flex gap-1.5">
                  <button onClick={() => void act('delete', async () => { await jobsApi.remove(job.id, false); onDeleted(job.id) })} className="btn-chip">Record only</button>
                  {job.outputs.length > 0 && (
                    <button onClick={() => void act('delete', async () => { await jobsApi.remove(job.id, true); onDeleted(job.id) })} className="btn-chip text-red-300">Record + files</button>
                  )}
                  <button onClick={() => setConfirmDelete(false)} className="btn-chip">Keep</button>
                </div>
              </div>
            )}
            {note && <p className="text-[11px] text-zinc-400 mt-1" role="status">{note}</p>}
          </Section>

          {job.prompt && (
            <Section title="Prompt">
              <p className="text-xs text-zinc-300 whitespace-pre-wrap bg-zinc-900 rounded p-2 border border-zinc-800">{job.prompt}</p>
              {job.negative_prompt && <p className="text-[11px] text-zinc-500 whitespace-pre-wrap">Negative: {job.negative_prompt}</p>}
            </Section>
          )}

          <Section title="Parameters">
            <KeyValue data={{ seed: job.seed, ...job.params }} />
          </Section>

          {Object.keys(job.metrics).length > 0 && (
            <Section title="Metrics">
              {Array.isArray(job.metrics.loss_history) && (
                <LossSparkline values={(job.metrics.loss_history as unknown[]).filter((v): v is number => typeof v === 'number')} width={300} height={56} />
              )}
              {typeof job.metrics.consistency === 'number' && (
                <p className="text-xs text-zinc-300" data-testid="consistency-score">Cross-frame consistency <span className={job.metrics.consistency >= 0.75 ? 'text-emerald-300' : job.metrics.consistency >= 0.5 ? 'text-amber-300' : 'text-red-300'}>{(job.metrics.consistency * 100).toFixed(0)}%</span> <span className="text-zinc-500">· CLIP similarity of the first frame to the character reference</span></p>
              )}
              <KeyValue data={{ ...job.metrics, loss_history: undefined, consistency: undefined, seconds: formatSeconds(job.metrics.seconds) || job.metrics.seconds }} />
            </Section>
          )}

          {Object.keys(job.inputs).length > 0 && (
            <Section title="Inputs">
              <KeyValue data={job.inputs} />
            </Section>
          )}

          {Object.keys(job.spec).length > 0 && (
            <Section title="Spec">
              <pre className="text-[10px] text-zinc-400 bg-zinc-900 rounded p-2 border border-zinc-800 overflow-x-auto max-h-48">{JSON.stringify(job.spec, null, 1)}</pre>
            </Section>
          )}

          {(loaded.lineage.length > 1 || loaded.children.length > 0) && (
            <Section title="Lineage">
              <ol className="space-y-1 text-xs" aria-label="Lineage chain">
                {loaded.lineage.map((ancestor, index) => (
                  <li key={ancestor.id} className="flex items-center gap-1.5" style={{ paddingLeft: index * 10 }}>
                    <GitBranch className="h-3 w-3 text-zinc-600" />
                    {ancestor.id === job.id ? (
                      <span className="text-zinc-200">{ancestor.title || JOB_KIND_LABEL[ancestor.kind]} (this job)</span>
                    ) : (
                      <button onClick={() => onSelect(ancestor.id)} className="text-violet-300 hover:underline text-left truncate">
                        {ancestor.title || JOB_KIND_LABEL[ancestor.kind]} · {ancestor.status}
                      </button>
                    )}
                  </li>
                ))}
                {loaded.children.map(child => (
                  <li key={child.id} className="flex items-center gap-1.5" style={{ paddingLeft: loaded.lineage.length * 10 }}>
                    <GitBranch className="h-3 w-3 text-zinc-600" />
                    <button onClick={() => onSelect(child.id)} className="text-violet-300 hover:underline text-left truncate">
                      {child.title || JOB_KIND_LABEL[child.kind]} · {child.status}
                    </button>
                  </li>
                ))}
              </ol>
            </Section>
          )}
        </div>
      )}

      {lightbox !== null && items.length > 0 && (
        <Lightbox items={items} index={Math.min(lightbox, items.length - 1)} onClose={() => setLightbox(null)} onIndexChange={setLightbox} />
      )}
    </aside>
  )
}
