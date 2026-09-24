import { useEffect, useState, useCallback } from 'react'
import { Activity, Loader2, Clock, Film, ImageIcon, ChevronDown, ChevronUp } from 'lucide-react'
import { backendFetch } from '../lib/backend'
import { filmOutputUrl } from '../lib/film-api'

interface ActiveJob {
  status: string
  phase: string
  progress: number
  currentStep?: number
  totalSteps?: number
  id?: string
  prompt?: string
}

interface RecentOutput {
  path: string
  prompt: string
  completed_at: number
  type: 'video' | 'image'
  size_mb: number
}

interface QueueState {
  active: ActiveJob | null
  recent: RecentOutput[]
}

function RecentPreview({ item }: { item: RecentOutput }) {
  const [url, setUrl] = useState('')
  useEffect(() => { let live = true; void filmOutputUrl(item.path).then(u => { if (live) setUrl(u) }).catch(() => {}); return () => { live = false } }, [item.path])
  if (!url) return <div className="h-12 w-16 rounded bg-zinc-800 flex items-center justify-center shrink-0">{item.type === 'video' ? <Film className="h-4 w-4 text-zinc-500" /> : <ImageIcon className="h-4 w-4 text-zinc-500" />}</div>
  return item.type === 'video'
    ? <video src={url} muted preload="metadata" controls className="h-12 w-16 rounded bg-black object-cover shrink-0" aria-label={`Recent video ${formatPath(item.path)}`} />
    : <a href={url} target="_blank" rel="noreferrer" title="Open full image"><img src={url} alt={formatPath(item.path)} className="h-12 w-16 rounded bg-black object-cover shrink-0" /></a>
}

function formatTime(ts: number): string {
  const diff = (Date.now() - ts) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago'
  return Math.floor(diff / 3600) + 'h ago'
}

function formatPath(path: string): string {
  const name = path.split(/[/\\]/).pop() ?? path
  if (name.length <= 50) return name
  return name.slice(0, 47) + '...'
}

export function ProcessingDashboard() {
  const [state, setState] = useState<QueueState>({ active: null, recent: [] })
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState('')

  const poll = useCallback(async () => {
    try {
      const res = await backendFetch('/api/generation/queue')
      if (!res.ok) return
      const data = await res.json() as QueueState
      setState(data)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void poll()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [poll])

  const isProcessing = !!state.active && ['running', 'queued'].includes(state.active.status)
  const hasActivity = isProcessing || state.recent.length > 0

  if (!hasActivity && !error) return null

  return (
    <div className="fixed bottom-4 right-4 z-50">
      {!expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="flex items-center gap-2 px-3 py-2 rounded-xl bg-zinc-900 border border-zinc-700 shadow-2xl hover:border-zinc-600 transition-colors"
        >
          {isProcessing ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400" />
              <span className="text-xs text-zinc-300">{state.active?.progress ?? 0}%</span>
            </>
          ) : (
            <Activity className="h-3.5 w-3.5 text-zinc-500" />
          )}
          <span className="text-[10px] text-zinc-400">
            {isProcessing ? 'In progress' : state.recent.length + ' recent'}
          </span>
          <ChevronUp className="h-3 w-3 text-zinc-600" />
        </button>
      )}

      {expanded && (
        <div className="w-80 rounded-xl bg-zinc-900 border border-zinc-700 shadow-2xl overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 bg-zinc-800/50 border-b border-zinc-700">
            <div className="flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-zinc-400" />
              <span className="text-[10px] font-semibold text-zinc-300 uppercase tracking-wide">Processing</span>
            </div>
            <button onClick={() => setExpanded(false)} className="p-0.5 rounded hover:bg-zinc-700 text-zinc-500 hover:text-zinc-300">
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
          </div>

          {error && <p className="px-3 py-2 text-[10px] text-red-400">{error}</p>}

          {state.active && isProcessing && (
            <div className="px-3 py-2 border-b border-zinc-800">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-zinc-400 capitalize">{state.active.status}</span>
                <span className="text-[10px] text-violet-400 font-medium">{state.active.progress}%</span>
              </div>
              <div className="w-full h-1 bg-zinc-800 rounded-full overflow-hidden">
                <div className="h-full bg-violet-500 rounded-full transition-all duration-500" style={{ width: state.active.progress + '%' }} />
              </div>
              <p className="text-[10px] text-zinc-500 mt-1">{state.active.phase}</p>
              {state.active.prompt && <p className="text-[10px] text-zinc-600 mt-0.5 truncate">{state.active.prompt.slice(0, 80)}</p>}
            </div>
          )}

          {state.recent.length > 0 && (
            <div className="max-h-48 overflow-y-auto">
              {state.recent.map((item, i) => (
                <div key={i} className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/30">
                  <RecentPreview item={item} />
                  <div className="min-w-0 flex-1">
                    <p className="text-[10px] text-zinc-400 truncate">{formatPath(item.path)}</p>
                    <p className="text-[9px] text-zinc-600 truncate">{item.prompt?.slice(0, 60) || 'No prompt'}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <span className="text-[9px] text-zinc-500">{item.size_mb.toFixed(1)} MB</span>
                    <div className="flex items-center gap-0.5 text-[9px] text-zinc-600"><Clock className="h-2.5 w-2.5" /> {formatTime(item.completed_at)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!isProcessing && !state.recent.length && <p className="px-3 py-3 text-[10px] text-zinc-600 text-center">Nothing processing right now</p>}
        </div>
      )}
    </div>
  )
}
