import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Cloud,
  Download,
  ExternalLink,
  HardDrive,
  Image as ImageIcon,
  KeyRound,
  Loader2,
  Search,
  Sparkles,
  Type,
  Video,
  X,
  XCircle,
} from 'lucide-react'
import { Button } from '../../components/ui/button'
import { useAppSettings, type AppSettings, type DirectorProviderSetting } from '../../contexts/AppSettingsContext'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi } from '../../lib/film-api'
import { modelLibraryApi } from '../../lib/model-library-api'
import { requestSettings } from '../../lib/error-messages'
import {
  LIBRARY_STATE_META,
  PROVIDER_DOC_URLS,
  type LibraryDownloadStatus,
  type LibraryModel,
  type LibraryTask,
  type MediaProviderId,
  type ModelSearchResponse,
} from '../../types/models'

type TaskFilter = 'all' | LibraryTask
type SourceFilter = 'all' | 'local' | 'hosted'

const TASK_TABS: { id: TaskFilter; label: string; icon: React.ReactNode }[] = [
  { id: 'all', label: 'All', icon: <Sparkles className="h-3 w-3" /> },
  { id: 'video', label: 'Video', icon: <Video className="h-3 w-3" /> },
  { id: 'image', label: 'Image', icon: <ImageIcon className="h-3 w-3" /> },
  { id: 'text', label: 'Text / script', icon: <Type className="h-3 w-3" /> },
]

function formatSize(gb: number | null): string {
  if (gb == null) return ''
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(gb * 1000)} MB`
}

function StateChip({ model }: { model: LibraryModel }) {
  const meta = LIBRARY_STATE_META[model.state] ?? LIBRARY_STATE_META.available
  return <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 ${meta.className}`}>{meta.label}</span>
}

/**
 * Search and install models: local weights that run offline (WanGP video/image,
 * the bundled LTX pipeline, Ollama text models) alongside the models each
 * configured hosted provider offers. Picking a row here sets what the film
 * actually generates with.
 */
export function ModelLibrary() {
  const { film, refresh, refreshCapabilities } = useFilm()
  const { settings, updateSettings, refreshSettings } = useAppSettings()
  const [query, setQuery] = useState('')
  const [task, setTask] = useState<TaskFilter>('all')
  const [source, setSource] = useState<SourceFilter>('all')
  const [onlyCompatible, setOnlyCompatible] = useState(false)
  const [data, setData] = useState<ModelSearchResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [download, setDownload] = useState<LibraryDownloadStatus | null>(null)
  const [customId, setCustomId] = useState('')
  const [customProvider, setCustomProvider] = useState('fal')
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(
    async (refreshRemote = false) => {
      setLoading(true)
      setError('')
      try {
        setData(await modelLibraryApi.search({ query, task, source, onlyCompatible, refresh: refreshRemote }))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [query, task, source, onlyCompatible],
  )

  // Debounce typing; filter changes apply immediately.
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => void load(false), query ? 250 : 0)
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current)
    }
  }, [load, query])

  // Follow a running download to completion, then re-list.
  useEffect(() => {
    if (!download?.active) return
    const interval = setInterval(async () => {
      try {
        const next = await modelLibraryApi.downloadStatus()
        setDownload(next)
        if (!next.active) {
          await load(true)
          await refreshCapabilities()
        }
      } catch {
        // transient polling failure; keep the last state
      }
    }, 1200)
    return () => clearInterval(interval)
  }, [download?.active, load, refreshCapabilities])

  const startDownload = useCallback(
    async (model: LibraryModel) => {
      setNote('')
      try {
        setDownload(await modelLibraryApi.startDownload(model.provider, model.id))
      } catch (e) {
        setNote(e instanceof Error ? e.message : String(e))
      }
    },
    [],
  )

  const cancelDownload = useCallback(async () => {
    try {
      setDownload(await modelLibraryApi.cancelDownload())
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    }
  }, [])

  /** Make this model the one the project (or the app) generates with. */
  const useModel = useCallback(
    async (model: LibraryModel) => {
      setNote('')
      try {
        await modelLibraryApi.remember(model.provider, model.id)
        if (model.task === 'text') {
          const providerMap: Record<string, string> = {
            openrouter: 'openrouter',
            anthropic: 'anthropic',
            xai: 'xai',
            gemini: 'gemini',
            ollama: 'openai_compatible',
            openai_compatible: 'openai_compatible',
          }
          const provider = providerMap[model.provider]
          if (!provider) {
            setNote(`${model.provider} cannot run the AI Director`)
            return
          }
          const patch: Partial<AppSettings> = { directorProvider: provider as DirectorProviderSetting }
          if (provider === 'openrouter') patch.openrouterModels = { ...settings.openrouterModels, defaultModel: model.id }
          if (provider === 'anthropic') patch.anthropicModel = model.id
          if (provider === 'xai') patch.xaiModel = model.id
          if (provider === 'gemini') patch.geminiModel = model.id
          if (provider === 'openai_compatible') patch.openaiCompatibleModel = model.id
          updateSettings(patch)
          setNote(`AI Director now uses ${model.id}`)
          return
        }

        const hosted = model.source === 'hosted'
        const mediaProvider: MediaProviderId = hosted ? (model.provider as 'fal' | 'wavespeed' | 'replicate') : 'local'
        if (film) {
          const next = {
            ...film.settings,
            media_provider: mediaProvider,
            ...(model.task === 'video' ? { video_model: hosted ? model.id : '' } : { image_model: hosted ? model.id : '' }),
            ...(model.task === 'video' && !hosted ? { default_model: model.provider === 'wangp' ? model.id : film.settings.default_model } : {}),
          }
          await filmApi.updateSettings(film.id, next)
          await refresh()
        }
        updateSettings({
          mediaProvider,
          ...(model.task === 'video' ? { defaultVideoModel: hosted ? model.id : '' } : { defaultImageModel: hosted ? model.id : '' }),
        })
        setNote(
          hosted
            ? `${model.task === 'video' ? 'Video' : 'Image'} generation now uses ${model.id} on ${model.provider}`
            : `${model.task === 'video' ? 'Video' : 'Image'} generation stays on this computer`,
        )
        await refreshSettings()
      } catch (e) {
        setNote(e instanceof Error ? e.message : String(e))
      }
    },
    [film, refresh, refreshSettings, settings.openrouterModels, updateSettings],
  )

  const addCustom = useCallback(async () => {
    const id = customId.trim()
    if (!id) return
    try {
      await modelLibraryApi.remember(customProvider, id)
      setCustomId('')
      setNote(`${id} added to the library`)
      await load(false)
      await refreshSettings()
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    }
  }, [customId, customProvider, load, refreshSettings])

  const unconfigured = useMemo(
    () => (data?.sources ?? []).filter(s => s.kind === 'hosted' && !s.configured).map(s => s.label),
    [data],
  )

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search models — name, id, family (ltx, flux, wan, claude, grok…)"
            aria-label="Search models"
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg pl-7 pr-7 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-700"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <Button size="sm" variant="secondary" onClick={() => void load(true)} disabled={loading} className="gap-1.5">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
          Refresh
        </Button>
      </div>

      <div className="flex items-center gap-2 flex-wrap text-[11px]">
        <div className="flex items-center rounded-lg border border-zinc-800 overflow-hidden" role="tablist" aria-label="Model type">
          {TASK_TABS.map(tab => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={task === tab.id}
              onClick={() => setTask(tab.id)}
              className={`flex items-center gap-1 px-2 py-1 ${task === tab.id ? 'bg-violet-600/70 text-white' : 'text-zinc-400 hover:bg-zinc-800'}`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex items-center rounded-lg border border-zinc-800 overflow-hidden" role="tablist" aria-label="Where it runs">
          {(
            [
              ['all', 'Anywhere', null],
              ['local', 'On this computer', <HardDrive key="l" className="h-3 w-3" />],
              ['hosted', 'Hosted (API key)', <Cloud key="h" className="h-3 w-3" />],
            ] as const
          ).map(([id, label, icon]) => (
            <button
              key={id}
              role="tab"
              aria-selected={source === id}
              onClick={() => setSource(id)}
              className={`flex items-center gap-1 px-2 py-1 ${source === id ? 'bg-violet-600/70 text-white' : 'text-zinc-400 hover:bg-zinc-800'}`}
            >
              {icon}
              {label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-zinc-400">
          <input type="checkbox" checked={onlyCompatible} onChange={e => setOnlyCompatible(e.target.checked)} />
          Only what fits this GPU
        </label>
        {data && (
          <span className="text-zinc-600 ml-auto">
            {data.total} model{data.total === 1 ? '' : 's'}
            {data.gpu_vram_gb != null ? ` · ${data.gpu_name ?? 'GPU'} ${data.gpu_vram_gb.toFixed(0)} GB` : ''}
          </span>
        )}
      </div>

      {data && (
        <div
          className={`rounded-lg border p-2 text-[11px] flex items-center gap-2 ${
            data.offline_ready ? 'border-emerald-900/60 bg-emerald-950/20 text-emerald-200' : 'border-zinc-800 bg-zinc-900/40 text-zinc-400'
          }`}
          role="status"
        >
          {data.offline_ready ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />}
          <span className="flex-1">{data.offline_note}</span>
          {unconfigured.length > 0 && (
            <button onClick={() => requestSettings('apiKeys')} className="underline underline-offset-2 hover:text-white">
              Add keys ({unconfigured.length} provider{unconfigured.length === 1 ? '' : 's'} idle)
            </button>
          )}
        </div>
      )}

      {download && download.status !== 'idle' && (
        <div className="rounded-lg border border-sky-900/60 bg-sky-950/20 p-2 space-y-1">
          <div className="flex items-center gap-2 text-[11px] text-sky-200">
            {download.active ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
            <span className="flex-1 truncate">
              {download.model_id} — {download.message || download.status}
              {download.files_total > 1 ? ` (file ${Math.min(download.files_done + 1, download.files_total)}/${download.files_total})` : ''}
            </span>
            {download.total_bytes > 0 && (
              <span className="tabular-nums text-sky-300">
                {(download.downloaded_bytes / 1_000_000_000).toFixed(2)} / {(download.total_bytes / 1_000_000_000).toFixed(2)} GB
              </span>
            )}
            {download.active && (
              <button onClick={() => void cancelDownload()} className="px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300">
                Cancel
              </button>
            )}
          </div>
          <div className="h-1 rounded bg-zinc-800 overflow-hidden">
            <div className="h-full bg-sky-500 transition-all" style={{ width: `${Math.round(download.progress * 100)}%` }} />
          </div>
          {download.error && <div className="text-[10px] text-red-300">{download.error}</div>}
        </div>
      )}

      {note && <div className="text-[11px] text-zinc-400" role="status">{note}</div>}
      {error && <div className="text-[11px] text-red-300">Could not load the library: {error}</div>}

      <div className="space-y-1">
        {(data?.models ?? []).map(model => (
          <div
            key={`${model.provider}:${model.id}`}
            className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/40 px-2.5 py-2"
          >
            <span className="shrink-0 text-zinc-500" title={model.source === 'local' ? 'Runs on this computer' : 'Runs on a hosted provider'}>
              {model.source === 'local' ? <HardDrive className="h-3.5 w-3.5" /> : <Cloud className="h-3.5 w-3.5" />}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-medium text-zinc-200 truncate">{model.name}</span>
                <span className="text-[10px] text-zinc-600 shrink-0">{model.provider}</span>
                {model.fits_gpu === false && (
                  <span className="flex items-center gap-0.5 text-[10px] text-red-400 shrink-0">
                    <XCircle className="h-3 w-3" /> needs ~{model.estimated_min_vram_gb?.toFixed(0)} GB VRAM
                  </span>
                )}
              </div>
              <div className="text-[10px] text-zinc-500 truncate font-mono">{model.id}</div>
              {(model.description || model.quantization || model.size_gb != null || model.context_length) && (
                <div className="text-[10px] text-zinc-600 truncate">
                  {[
                    model.description,
                    model.quantization,
                    formatSize(model.size_gb),
                    model.context_length ? `${Math.round(model.context_length / 1000)}k context` : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </div>
              )}
            </div>
            <StateChip model={model} />
            {model.url && (
              <a
                href={model.url}
                target="_blank"
                rel="noreferrer"
                title="Open the provider's model page"
                className="text-zinc-500 hover:text-zinc-300 shrink-0"
              >
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
            {model.downloadable && (
              <button
                onClick={() => void startDownload(model)}
                disabled={download?.active}
                className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[10px] text-zinc-200 shrink-0"
              >
                <Download className="h-3 w-3" /> Download
              </button>
            )}
            {model.provider === 'ollama' && !model.installed && (
              <button
                onClick={() => void startDownload(model)}
                disabled={download?.active}
                className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[10px] text-zinc-200 shrink-0"
              >
                <Download className="h-3 w-3" /> Pull
              </button>
            )}
            {model.state === 'needs_key' ? (
              <button
                onClick={() => requestSettings('apiKeys')}
                className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-amber-300 shrink-0"
              >
                <KeyRound className="h-3 w-3" /> Add key
              </button>
            ) : (
              <button
                onClick={() => void useModel(model)}
                className="px-2 py-1 rounded bg-violet-700 hover:bg-violet-600 text-[10px] text-white shrink-0"
                title={model.task === 'text' ? 'Use for the AI Director' : `Use for ${model.task} generation in this film`}
              >
                Use
              </button>
            )}
          </div>
        ))}
        {!loading && data && data.models.length === 0 && (
          <div className="text-[11px] text-zinc-500 py-6 text-center">
            No models match. Clear the filters, or paste a model id from your provider below.
          </div>
        )}
      </div>

      {/* Any id the provider accepts works, even when it is not in a catalog. */}
      <div className="flex items-center gap-2 pt-1 border-t border-zinc-800">
        <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Add by id</span>
        <select
          value={customProvider}
          onChange={e => setCustomProvider(e.target.value)}
          aria-label="Provider for the custom model id"
          className="bg-zinc-900 border border-zinc-800 rounded px-1.5 py-1 text-[11px] text-zinc-200"
        >
          {['fal', 'wavespeed', 'replicate', 'openrouter', 'anthropic', 'xai', 'gemini', 'ollama'].map(provider => (
            <option key={provider} value={provider}>
              {provider}
            </option>
          ))}
        </select>
        <input
          value={customId}
          onChange={e => setCustomId(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') void addCustom()
          }}
          placeholder="e.g. fal-ai/ltx-video-13b-distilled"
          aria-label="Custom model id"
          className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-[11px] text-zinc-200 placeholder:text-zinc-600 font-mono"
        />
        <button
          onClick={() => void addCustom()}
          disabled={!customId.trim()}
          className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[11px] text-zinc-200"
        >
          Add
        </button>
        {PROVIDER_DOC_URLS[customProvider] && (
          <a
            href={PROVIDER_DOC_URLS[customProvider]}
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-zinc-500 hover:text-zinc-300 underline underline-offset-2 whitespace-nowrap"
          >
            {customProvider} catalog
          </a>
        )}
      </div>

      {data && (
        <div className="text-[10px] text-zinc-600 leading-relaxed">
          {data.sources
            .filter(s => s.error)
            .map(s => (
              <div key={s.id} className="text-amber-400/80">
                {s.label}: {s.error}
              </div>
            ))}
          Local weights install to <code className="text-zinc-500">{data.models_path}</code>. Example ids are starting
          points — check the provider's catalog for the exact id.
        </div>
      )}
    </div>
  )
}
