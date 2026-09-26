import { useEffect, useState } from 'react'
import { AlertTriangle, Clock, Download, FileVideo, ImageIcon, Loader2, RefreshCw, ScanSearch, Sparkles, XCircle } from 'lucide-react'
import { filmOutputUrl } from '../../lib/film-api'
import { JOB_KIND_LABEL, isActive, type Job, type JobKind } from '../../types/jobs'

export const KIND_ICON: Record<JobKind, React.ReactNode> = {
  image_gen: <ImageIcon className="h-3.5 w-3.5" />,
  video_gen: <FileVideo className="h-3.5 w-3.5" />,
  image_reproduce: <RefreshCw className="h-3.5 w-3.5" />,
  video_reproduce: <RefreshCw className="h-3.5 w-3.5" />,
  analysis: <ScanSearch className="h-3.5 w-3.5" />,
  scene_build: <Sparkles className="h-3.5 w-3.5" />,
  training: <Sparkles className="h-3.5 w-3.5" />,
  download: <Download className="h-3.5 w-3.5" />,
}

export function statusTone(job: Job): string {
  switch (job.status) {
    case 'complete':
      return 'text-emerald-300'
    case 'failed':
      return 'text-red-300'
    case 'cancelled':
      return 'text-zinc-400'
    case 'running':
      return 'text-violet-300'
    default:
      return 'text-amber-300'
  }
}

export function formatWhen(ms: number): string {
  const date = new Date(ms)
  const today = new Date()
  const sameDay = date.toDateString() === today.toDateString()
  return sameDay ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function formatSeconds(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  return value >= 60 ? `${Math.floor(value / 60)}m ${Math.round(value % 60)}s` : `${value.toFixed(value < 10 ? 1 : 0)}s`
}

/** Resolve the first output's thumbnail (or the output itself for images) to a loadable URL. */
export function useJobThumb(job: Job): { url: string | null; kind: 'image' | 'video' | 'file' | null; error: boolean } {
  const first = job.outputs[0]
  const source = first?.thumb || (first?.kind === 'image' ? first.path : '')
  const [state, setState] = useState<{ url: string | null; error: boolean }>({ url: null, error: false })
  useEffect(() => {
    let cancelled = false
    if (!source) {
      setState({ url: null, error: false })
      return
    }
    filmOutputUrl(source)
      .then(url => { if (!cancelled) setState({ url, error: false }) })
      .catch(() => { if (!cancelled) setState({ url: null, error: true }) })
    return () => { cancelled = true }
  }, [source])
  return { url: state.url, kind: first?.kind ?? null, error: state.error }
}

interface JobCardProps {
  job: Job
  selected: boolean
  onOpen: () => void
  onCancel?: () => void
}

export function JobCard({ job, selected, onOpen, onCancel }: JobCardProps) {
  const { url, kind, error } = useJobThumb(job)
  const [imgFailed, setImgFailed] = useState(false)
  useEffect(() => setImgFailed(false), [url])
  const active = isActive(job)
  const label = job.title || job.prompt || JOB_KIND_LABEL[job.kind]

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${JOB_KIND_LABEL[job.kind]} job: ${label}`}
      data-testid="job-card"
      data-job-id={job.id}
      data-status={job.status}
      onClick={onOpen}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}
      className={
        'group relative rounded-xl overflow-hidden border bg-zinc-900/60 cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-violet-500/50 ' +
        (selected ? 'border-violet-500' : 'border-zinc-800 hover:border-zinc-600')
      }
    >
      <div className="aspect-video bg-zinc-950 relative flex items-center justify-center">
        {url && !imgFailed ? (
          <img
            src={url}
            alt=""
            loading="lazy"
            onError={() => setImgFailed(true)}
            className="w-full h-full object-cover"
          />
        ) : error || imgFailed ? (
          <div className="flex flex-col items-center text-red-300 text-[11px] gap-1" role="img" aria-label="Preview unavailable">
            <AlertTriangle className="h-4 w-4" /> preview unavailable
          </div>
        ) : active ? (
          <div className="flex flex-col items-center gap-2 text-zinc-400 text-xs">
            <Loader2 className="h-5 w-5 animate-spin text-violet-400" />
            <span>{job.phase || job.status}</span>
          </div>
        ) : (
          <span className="text-zinc-700">{KIND_ICON[job.kind]}</span>
        )}
        {kind === 'video' && url && (
          <span className="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 rounded bg-black/70 text-[10px] text-zinc-200">
            {job.outputs[0]?.duration ? `${job.outputs[0].duration.toFixed(1)}s` : 'video'}
          </span>
        )}
        {active && (
          <div className="absolute inset-x-0 bottom-0 h-1 bg-zinc-800" role="progressbar" aria-valuenow={Math.round(job.progress)} aria-valuemin={0} aria-valuemax={100} aria-label="Job progress">
            <div className="h-full bg-violet-500 transition-all" style={{ width: `${Math.max(2, job.progress)}%` }} />
          </div>
        )}
        <span className="absolute top-1.5 left-1.5 flex items-center gap-1 px-1.5 py-0.5 rounded bg-black/60 text-[10px] text-zinc-200">
          {KIND_ICON[job.kind]} {JOB_KIND_LABEL[job.kind]}
        </span>
        {active && onCancel && (
          <button
            onClick={e => { e.stopPropagation(); onCancel() }}
            aria-label={`Cancel ${label}`}
            className="absolute top-1.5 right-1.5 p-1 rounded bg-black/60 text-zinc-300 hover:text-red-300"
          >
            <XCircle className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="p-2 space-y-0.5">
        <p className="text-xs text-zinc-200 truncate" title={label}>{label}</p>
        <p className="text-[10px] text-zinc-500 flex items-center gap-1.5 truncate">
          <span className={statusTone(job)}>{job.status}{active ? ` ${Math.round(job.progress)}%` : ''}</span>
          {job.model && <span className="truncate">· {job.model}</span>}
          <span className="ml-auto flex items-center gap-1 shrink-0"><Clock className="h-3 w-3" />{formatWhen(job.created_at)}</span>
        </p>
      </div>
    </div>
  )
}
