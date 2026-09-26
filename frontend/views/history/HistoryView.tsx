import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, History, Loader2, Search, Wifi, WifiOff } from 'lucide-react'
import { useProjects } from '../../contexts/ProjectContext'
import { jobsApi } from '../../lib/jobs-api'
import { logger } from '../../lib/logger'
import { JOB_KINDS, JOB_KIND_LABEL, isActive, type Job, type JobKind } from '../../types/jobs'
import { JobCard } from './JobCard'
import { JobDrawer } from './JobDrawer'
import { useJobs } from './useJobs'

type Bucket = 'all' | 'active' | 'complete' | 'failed'
type DateRange = 'any' | 'today' | 'week' | 'month'

const BUCKETS: { id: Bucket; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'active', label: 'In progress' },
  { id: 'complete', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
]

function withinRange(job: Job, range: DateRange): boolean {
  if (range === 'any') return true
  const age = Date.now() - job.created_at
  const day = 24 * 60 * 60 * 1000
  return range === 'today' ? age < day : range === 'week' ? age < 7 * day : age < 31 * day
}

/**
 * Every job the app ran, across every mode, from one store. In-progress jobs
 * update live (SSE, or polling when the stream is unavailable).
 */
export function HistoryView() {
  const { goHome, openAnalysis, openProject, openQuickMode, setQuickPreset } = useProjects()
  const [bucket, setBucket] = useState<Bucket>('all')
  const [kind, setKind] = useState<JobKind | ''>('')
  const [model, setModel] = useState('')
  const [project, setProject] = useState('')
  const [range, setRange] = useState<DateRange>('any')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(search.trim()), 250)
    return () => window.clearTimeout(id)
  }, [search])

  const query = useMemo(
    () => ({
      kind: kind || undefined,
      status: bucket === 'all' ? undefined : bucket === 'failed' ? 'failed' : bucket,
      project: project || undefined,
      q: debounced || undefined,
    }),
    [kind, bucket, project, debounced],
  )
  const { jobs, loading, error, nextCursor, feedMode, refresh, loadMore } = useJobs(query)

  const models = useMemo(() => Array.from(new Set(jobs.map(j => j.model).filter(Boolean))).sort(), [jobs])
  const projects = useMemo(() => Array.from(new Set(jobs.map(j => j.project_id).filter(Boolean))).sort(), [jobs])
  const visible = useMemo(
    () => jobs.filter(j => (!model || j.model === model) && withinRange(j, range) && (bucket !== 'failed' || j.status === 'failed' || j.status === 'cancelled')),
    [jobs, model, range, bucket],
  )
  const activeCount = useMemo(() => jobs.filter(isActive).length, [jobs])

  const cancel = useCallback(async (job: Job) => {
    try {
      await jobsApi.cancel(job.id)
    } catch (err) {
      logger.warn(`Cancel failed: ${err}`)
    }
  }, [])

  const openReproduce = useCallback((job: Job) => {
    const analysisId = typeof job.inputs.analysis_id === 'string' ? job.inputs.analysis_id : ''
    const isImage = job.kind === 'image_reproduce' || job.kind === 'image_gen'
    openAnalysis(isImage ? 'image' : 'video', analysisId)
  }, [openAnalysis])

  const openStoryboard = useCallback((job: Job) => {
    if (job.project_id) openProject(job.project_id, 'storyboard')
  }, [openProject])

  const openQuick = useCallback((job: Job) => {
    setQuickPreset({ prompt: job.prompt, negativePrompt: job.negative_prompt, params: job.params, seed: job.seed })
    openQuickMode()
  }, [openQuickMode, setQuickPreset])

  return (
    <div className="h-screen w-screen flex flex-col bg-zinc-950 text-zinc-100">
      <header className="flex items-center gap-3 px-4 py-3 border-b border-zinc-800">
        <button onClick={goHome} aria-label="Back to home" className="p-2 rounded-lg hover:bg-zinc-800 transition-colors">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <History className="h-4 w-4 text-violet-400" />
        <h1 className="text-sm font-semibold">History</h1>
        <span className="text-xs text-zinc-500">{activeCount > 0 ? `${activeCount} in progress` : `${jobs.length} job${jobs.length === 1 ? '' : 's'}`}</span>
        <span className="ml-auto flex items-center gap-1 text-[10px] text-zinc-500" title={feedMode === 'sse' ? 'Live updates over server-sent events' : feedMode === 'poll' ? 'Live updates by polling' : 'Connecting'}>
          {feedMode === 'connecting' ? <Loader2 className="h-3 w-3 animate-spin" /> : feedMode === 'sse' ? <Wifi className="h-3 w-3 text-emerald-400" /> : <WifiOff className="h-3 w-3 text-amber-400" />}
          {feedMode === 'sse' ? 'live' : feedMode === 'poll' ? 'polling' : 'connecting'}
        </span>
      </header>

      <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800 flex-wrap">
        <div className="flex items-center gap-0.5 bg-zinc-900 rounded-lg p-0.5" role="tablist" aria-label="Job status">
          {BUCKETS.map(b => (
            <button key={b.id} role="tab" aria-selected={bucket === b.id} onClick={() => setBucket(b.id)}
              className={'px-2.5 py-1 rounded-md text-xs ' + (bucket === b.id ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:text-white')}>
              {b.label}
            </button>
          ))}
        </div>
        <select aria-label="Filter by kind" value={kind} onChange={e => setKind(e.target.value as JobKind | '')} className="select-chip">
          <option value="">All kinds</option>
          {JOB_KINDS.map(k => <option key={k} value={k}>{JOB_KIND_LABEL[k]}</option>)}
        </select>
        <select aria-label="Filter by model" value={model} onChange={e => setModel(e.target.value)} className="select-chip">
          <option value="">All models</option>
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <select aria-label="Filter by date" value={range} onChange={e => setRange(e.target.value as DateRange)} className="select-chip">
          <option value="any">Any time</option>
          <option value="today">Today</option>
          <option value="week">This week</option>
          <option value="month">This month</option>
        </select>
        {projects.length > 0 && (
          <select aria-label="Filter by project" value={project} onChange={e => setProject(e.target.value)} className="select-chip">
            <option value="">All projects</option>
            {projects.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        )}
        <label className="ml-auto flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 rounded-lg px-2 py-1 text-xs">
          <Search className="h-3.5 w-3.5 text-zinc-500" />
          <input aria-label="Search prompts" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search prompts…" className="bg-transparent outline-none w-48 placeholder:text-zinc-600" />
        </label>
      </div>

      <div className="flex-1 min-h-0 flex">
        <main className="flex-1 min-w-0 overflow-y-auto p-4">
          {error && <p className="text-xs text-red-300 mb-3" role="alert">{error} <button onClick={() => void refresh()} className="underline">retry</button></p>}
          {loading && jobs.length === 0 ? (
            <div className="h-full flex items-center justify-center text-zinc-500 text-sm"><Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading history…</div>
          ) : visible.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <History className="h-8 w-8 text-zinc-800 mb-2" />
              <p className="text-sm text-zinc-400">{jobs.length === 0 ? 'Nothing here yet' : 'No jobs match these filters'}</p>
              <p className="text-xs text-zinc-600 mt-1 max-w-sm">{jobs.length === 0 ? 'Every image, video, analysis, download and training run shows up here as it happens.' : 'Try another kind, model or time range.'}</p>
            </div>
          ) : (
            <>
              <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(200px,1fr))]" data-testid="job-grid">
                {visible.map(job => (
                  <JobCard key={job.id} job={job} selected={selectedId === job.id} onOpen={() => setSelectedId(job.id)} onCancel={isActive(job) ? () => void cancel(job) : undefined} />
                ))}
              </div>
              {nextCursor && (
                <div className="flex justify-center mt-4">
                  <button onClick={() => void loadMore()} className="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs">Load more</button>
                </div>
              )}
            </>
          )}
        </main>
        {selectedId && (
          <JobDrawer
            jobId={selectedId}
            onClose={() => setSelectedId(null)}
            onSelect={setSelectedId}
            onOpenReproduce={openReproduce}
            onOpenProject={openStoryboard}
            onOpenQuick={openQuick}
            onDeleted={() => { setSelectedId(null); void refresh() }}
          />
        )}
      </div>
    </div>
  )
}
