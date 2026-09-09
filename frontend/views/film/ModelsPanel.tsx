import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Cloud,
  Cpu,
  Download,
  FolderOpen,
  Gauge,
  HardDrive,
  Info,
  Loader2,
  Settings2,
  Trash2,
  XCircle,
} from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { backendFetch } from '../../lib/backend'
import { filmApi } from '../../lib/film-api'
import { Button } from '../../components/ui/button'
import type { FilmModelCapability } from '../../types/film'
import { ModelLibrary } from './ModelLibrary'

interface DownloadProgress {
  status: string
  currentFile: string
  totalProgress: number
  downloadedBytes: number
  totalBytes: number
  speedMbps: number
  error: string | null
}

function FitBadge({ model }: { model: FilmModelCapability }) {
  if (model.fits_gpu === false) {
    return (
      <span
        className="flex items-center gap-1 text-[10px] text-red-400"
        title={`Needs ~${model.estimated_min_vram_gb?.toFixed(0)} GB VRAM — more than the detected GPU has`}
      >
        <XCircle className="h-3 w-3" /> Incompatible with this GPU
      </span>
    )
  }
  if (model.fits_gpu === true) {
    return (
      <span className="flex items-center gap-1 text-[10px] text-emerald-400">
        <CheckCircle2 className="h-3 w-3" /> Fits this GPU
      </span>
    )
  }
  if (model.execution === 'api') return null
  return (
    <span className="flex items-center gap-1 text-[10px] text-zinc-500" title="GPU VRAM not detected">
      <Info className="h-3 w-3" /> Fit unknown
    </span>
  )
}

/**
 * One state per model row, in the vocabulary the product uses: ACTIVE (the
 * configured model), INSTALLED, AVAILABLE (WanGP fetches it on first use /
 * the app can download it), DOWNLOADING, UPDATE AVAILABLE, INCOMPATIBLE.
 * `download_state` is the raw mechanism (how the weights get here).
 */
function StateChip({ model, downloading }: { model: FilmModelCapability; downloading: boolean }) {
  const state = downloading && !model.downloaded && model.execution === 'local' ? 'downloading' : model.state
  const map: Record<string, { label: string; className: string }> = {
    active: { label: 'Active', className: 'bg-violet-900/60 text-violet-200' },
    installed: { label: 'Installed', className: 'bg-emerald-900/60 text-emerald-300' },
    available: { label: 'Available', className: 'bg-zinc-800 text-zinc-300' },
    downloading: { label: 'Downloading', className: 'bg-sky-900/60 text-sky-300' },
    update_available: { label: 'Update available', className: 'bg-amber-950/70 text-amber-300' },
    incompatible: { label: 'Incompatible', className: 'bg-red-950/70 text-red-300' },
  }
  const fallback: Record<FilmModelCapability['download_state'], { label: string; className: string }> = {
    downloaded: map.installed,
    not_downloaded: map.available,
    managed_by_wangp: map.available,
    cloud: { label: 'Cloud', className: 'bg-sky-900/60 text-sky-300' },
    not_configured: { label: 'Needs WanGP setup', className: 'bg-amber-950/70 text-amber-300' },
  }
  const meta = map[state] ?? fallback[model.download_state]
  const mechanism =
    model.download_state === 'managed_by_wangp'
      ? 'WanGP downloads the weights on first use'
      : model.download_state === 'cloud'
        ? 'Runs in the LTX cloud — nothing to install'
        : model.download_state === 'not_configured'
          ? 'Set WANGP_ROOT to enable'
          : undefined
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${meta.className}`} title={mechanism}>
      {meta.label}
    </span>
  )
}

/** Project-wide render defaults: quality profile, preview size, gap, strict continuity. */
function FilmRenderSettingsCard() {
  const { film, setFilm, capabilities } = useFilm()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  if (!film) return null
  const settings = film.settings

  const update = async (patch: Partial<typeof settings>) => {
    setSaving(true)
    setError('')
    try {
      setFilm(await filmApi.updateSettings(film.id, { ...settings, ...patch }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const selectClass =
    'bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-violet-600 disabled:opacity-50'

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Settings2 className="h-4 w-4 text-violet-400" />
        <span className="text-xs font-semibold text-white">Project render defaults</span>
        {saving && <Loader2 className="h-3 w-3 animate-spin text-zinc-500" />}
        {error && <span className="text-[10px] text-red-400 truncate">{error}</span>}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-[11px] text-zinc-400">
        <label className="flex items-center justify-between gap-2">
          <span>Default quality profile</span>
          <select
            value={settings.default_quality_preset}
            disabled={saving}
            onChange={e => void update({ default_quality_preset: e.target.value as typeof settings.default_quality_preset })}
            className={selectClass}
            aria-label="Default quality profile"
          >
            {(capabilities?.profiles ?? []).map(p => (
              <option key={p.id} value={p.id}>
                {p.label}
                {p.recommended ? ' (recommended)' : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center justify-between gap-2">
          <span>Preview resolution</span>
          <select
            value={settings.preview_resolution}
            disabled={saving}
            onChange={e => void update({ preview_resolution: e.target.value })}
            className={selectClass}
            aria-label="Preview resolution"
          >
            {['540p', '720p', '1080p'].map(r => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center justify-between gap-2">
          <span>Preview max seconds</span>
          <input
            type="number"
            min={1}
            max={20}
            step={1}
            value={settings.preview_max_seconds}
            disabled={saving}
            onChange={e => void update({ preview_max_seconds: Math.max(1, Number(e.target.value) || 4) })}
            className={`${selectClass} w-16 text-center`}
            aria-label="Preview max seconds"
          />
        </label>
        <label className="flex items-center justify-between gap-2">
          <span>Gap between shots on the timeline (s)</span>
          <input
            type="number"
            min={0}
            max={10}
            step={0.5}
            value={settings.inter_shot_gap_seconds}
            disabled={saving}
            onChange={e => void update({ inter_shot_gap_seconds: Math.max(0, Number(e.target.value) || 0) })}
            className={`${selectClass} w-16 text-center`}
            aria-label="Gap between shots"
          />
        </label>
        <label className="flex items-center justify-between gap-2 col-span-2">
          <span>
            Strict continuity <span className="text-zinc-600">— refuse to render shots with continuity warnings</span>
          </span>
          <input
            type="checkbox"
            checked={settings.strict_continuity}
            disabled={saving}
            onChange={e => void update({ strict_continuity: e.target.checked })}
            aria-label="Strict continuity"
          />
        </label>
      </div>
    </div>
  )
}

/**
 * VRAM-aware model manager: detects the GPU, states a compatibility verdict,
 * lists every model path with real on-disk sizes and per-model fit against
 * the detected VRAM, and downloads missing required models through the
 * existing /api/models/download pipeline.
 */
export function ModelsPanel() {
  const { capabilities, refreshCapabilities } = useFilm()
  const [view, setView] = useState<'library' | 'installed'>('library')
  const [progress, setProgress] = useState<DownloadProgress | null>(null)
  const [starting, setStarting] = useState(false)
  const [skipTextEncoder, setSkipTextEncoder] = useState(false)
  const [skipDefaultApplied, setSkipDefaultApplied] = useState(false)
  const [note, setNote] = useState('')
  const [removing, setRemoving] = useState<string | null>(null)

  const downloading = progress?.status === 'downloading'

  // When the text encoder is optional (cloud encoding available), default to
  // skipping its very large download; the user can still opt in.
  useEffect(() => {
    if (capabilities && !skipDefaultApplied) {
      setSkipTextEncoder(capabilities.text_encoder_optional)
      setSkipDefaultApplied(true)
    }
  }, [capabilities, skipDefaultApplied])

  // Poll download progress while the panel is open; refresh capabilities on completion.
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const response = await backendFetch('/api/models/download/progress')
        if (response.ok) {
          const data = (await response.json()) as DownloadProgress
          setProgress(data)
          if (data.status === 'complete') {
            await refreshCapabilities()
          }
        }
      } catch {
        // ignore transient polling errors
      }
    }, 1500)
    return () => clearInterval(interval)
  }, [refreshCapabilities])

  const removeModel = useCallback(
    async (model: FilmModelCapability) => {
      if (!window.confirm(`Remove ${model.label} from disk? You can download it again later.`)) return
      setRemoving(model.id)
      setNote('')
      try {
        await filmApi.removeModel(model.id)
        await refreshCapabilities()
        setNote(`${model.label} removed`)
      } catch (e) {
        setNote(`Could not remove: ${e instanceof Error ? e.message : e}`)
      } finally {
        setRemoving(null)
      }
    },
    [refreshCapabilities],
  )

  const startDownload = useCallback(async () => {
    setStarting(true)
    setNote('')
    try {
      const response = await backendFetch('/api/models/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skipTextEncoder }),
      })
      if (!response.ok) {
        throw new Error(await response.text())
      }
      setNote('Download started')
    } catch (e) {
      setNote(`Could not start download: ${e instanceof Error ? e.message : e}`)
    } finally {
      setStarting(false)
    }
  }, [skipTextEncoder])

  if (!capabilities) {
    return (
      <div className="h-full flex items-center justify-center text-zinc-500">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    )
  }

  const anyNotDownloaded = capabilities.models.some(m => m.download_state === 'not_downloaded')
  const verdictStyle =
    capabilities.gpu_verdict_level === 'ok'
      ? 'border-emerald-900/60 bg-emerald-950/30 text-emerald-300'
      : capabilities.gpu_verdict_level === 'partial'
        ? 'border-amber-900/60 bg-amber-950/30 text-amber-300'
        : 'border-red-900/60 bg-red-950/30 text-red-300'

  const textEncoderRow = capabilities.models.find(m => m.id === 'text_encoder')
  // The backend total covers the *required* set; an optional (skippable) text
  // encoder is added on top only when the user chooses to include it.
  const encoderExtraGb =
    capabilities.text_encoder_optional && textEncoderRow && !textEncoderRow.downloaded && !skipTextEncoder
      ? (textEncoderRow.disk_size_gb ?? 0)
      : 0
  const downloadSize = (capabilities.total_required_download_gb ?? 0) + encoderExtraGb

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="max-w-2xl mx-auto space-y-4">
        <div className="flex items-center rounded-lg border border-zinc-800 overflow-hidden w-fit" role="tablist" aria-label="Models view">
          {(
            [
              ['library', 'Model Library'],
              ['installed', 'Installed & GPU'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={view === id}
              onClick={() => setView(id)}
              className={`px-3 py-1.5 text-xs font-medium ${view === id ? 'bg-zinc-800 text-white' : 'text-zinc-500 hover:text-zinc-300'}`}
            >
              {label}
            </button>
          ))}
        </div>

        {view === 'library' && <ModelLibrary />}

        {view === 'installed' && (
        <>
        {/* GPU summary */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 flex items-center gap-3">
          <Cpu className="h-5 w-5 text-violet-400" />
          <div className="flex-1">
            <div className="text-sm font-medium text-white">
              {capabilities.gpu_name ?? 'No CUDA GPU detected'}
            </div>
            <div className="text-[11px] text-zinc-500">
              {capabilities.gpu_vram_gb != null
                ? `${capabilities.gpu_vram_gb.toFixed(0)} GB VRAM`
                : 'VRAM unknown'}
              {' · '}
              {capabilities.execution_mode === 'wangp'
                ? 'WanGP bridge (models managed by WanGP)'
                : capabilities.execution_mode === 'api'
                  ? 'API-only mode (cloud generation)'
                  : 'Local generation'}
            </div>
          </div>
        </div>

        {/* Compatibility verdict for the detected GPU */}
        <div className={`rounded-lg border p-3 text-xs leading-relaxed ${verdictStyle}`}>
          {capabilities.gpu_verdict}
        </div>

        {/* Where the weights live + system summary */}
        <div className="flex items-center gap-2 text-[11px] text-zinc-500">
          <FolderOpen className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate font-mono" title={capabilities.models_path}>
            {capabilities.models_path}
          </span>
          <button
            onClick={() => void window.electronAPI?.showItemInFolder(capabilities.models_path)}
            className="px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300 whitespace-nowrap"
            title="Reveal the model folder in the file manager"
          >
            Open model location
          </button>
          <span className="flex-1" />
          <span className="whitespace-nowrap">
            {capabilities.system_ram_gb != null ? `${capabilities.system_ram_gb.toFixed(0)} GB RAM` : 'RAM unknown'} ·{' '}
            {capabilities.cuda_available ? 'CUDA available' : 'no CUDA'}
          </span>
        </div>
        {capabilities.execution_mode === 'wangp' && (
          <p className="text-[11px] text-zinc-500 leading-relaxed">
            Models listed as <span className="text-zinc-300">Available</span> come from the WanGP checkout's own
            definitions (<code className="text-zinc-400">defaults/*.json</code>); WanGP downloads their weights
            into <code className="text-zinc-400">ckpts/</code> the first time they are used. Switch the active model
            with <code className="text-zinc-400">WANGP_VIDEO_MODEL_TYPE</code>.
          </p>
        )}

        {/* Model list with per-model fit */}
        <div className="space-y-2">
          {capabilities.models.map(model => (
            <div
              key={model.id}
              className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 flex items-center gap-3"
            >
              {model.execution === 'api' ? (
                <Cloud className="h-4 w-4 text-sky-400 shrink-0" />
              ) : (
                <HardDrive className="h-4 w-4 text-zinc-500 shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-zinc-200 truncate">
                  {model.label}
                  {!model.required && model.download_state !== 'not_configured' && !model.is_active && (
                    <span className="ml-1.5 text-[10px] text-zinc-600">(optional)</span>
                  )}
                </div>
                <div className="text-[11px] text-zinc-500">
                  {model.modes.join(' + ')}
                  {model.family && ` · ${model.family}`}
                  {model.quantization && ` · ${model.quantization}`}
                  {model.disk_size_gb != null && ` · ${model.disk_size_gb.toFixed(0)} GB on disk`}
                  {model.estimated_min_vram_gb != null &&
                    ` · needs ~${model.estimated_min_vram_gb.toFixed(0)} GB VRAM${model.vram_is_estimate ? ' (estimate)' : ''}`}
                  {model.supported_resolutions.length > 0 &&
                    ` · up to ${model.supported_resolutions[model.supported_resolutions.length - 1]}`}
                </div>
                {model.description && model.execution === 'wangp' && (
                  <div className="text-[10px] text-zinc-600 mt-0.5 truncate" title={model.description}>
                    {model.description}
                  </div>
                )}
                {model.download_state === 'not_configured' && (
                  <div className="text-[10px] text-amber-400/80 mt-0.5">
                    Runs LTX on 6 GB+ GPUs. Set WANGP_ROOT to a WanGP checkout — see the README's
                    WanGP quick start.
                  </div>
                )}
              </div>
              <FitBadge model={model} />
              <StateChip model={model} downloading={downloading} />
              {model.execution === 'local' && model.downloaded && (
                <button
                  onClick={() => void removeModel(model)}
                  disabled={downloading || removing === model.id}
                  className="p-1 rounded text-zinc-600 hover:text-red-400 hover:bg-red-950/40 disabled:opacity-40"
                  title="Remove this model from disk (re-download later to update)"
                  aria-label={`Remove ${model.label}`}
                >
                  {removing === model.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                </button>
              )}
            </div>
          ))}
        </div>

        {/* Quality profiles for this GPU */}
        {capabilities.profiles.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <Gauge className="h-4 w-4 text-violet-400" />
              <span className="text-xs font-semibold text-white">Quality profiles</span>
              <span className="text-[10px] text-zinc-600">final renders use the shot's profile, or the project default</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              {capabilities.profiles
                .filter(p => p.id !== 'custom')
                .map(profile => (
                  <div
                    key={profile.id}
                    className={`rounded border p-2 ${profile.recommended ? 'border-violet-700 bg-violet-950/20' : 'border-zinc-800'}`}
                  >
                    <div className="flex items-center gap-1.5 text-xs text-zinc-200">
                      {profile.label}
                      <span className="text-[10px] text-zinc-500 font-mono">
                        {profile.model} @ {profile.resolution}
                      </span>
                      {profile.recommended && <span className="ml-auto text-[10px] text-violet-300">recommended</span>}
                      {profile.fits_gpu === false && <span className="ml-auto text-[10px] text-red-400">may not fit VRAM</span>}
                    </div>
                    <div className="text-[10px] text-zinc-500 mt-0.5">{profile.description}</div>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Download control */}
        {capabilities.execution_mode === 'local' && anyNotDownloaded && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 space-y-2">
            {downloading && progress ? (
              <>
                <div className="flex items-center gap-2 text-xs text-zinc-300">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Downloading {progress.currentFile} · {progress.speedMbps} MB/s ·{' '}
                  {progress.totalProgress}%
                </div>
                <div className="h-1.5 rounded bg-zinc-800 overflow-hidden">
                  <div
                    className="h-full bg-violet-600 transition-all"
                    style={{ width: `${progress.totalProgress}%` }}
                  />
                </div>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  onClick={() => void startDownload()}
                  disabled={starting || downloadSize <= 0}
                  className="gap-1.5"
                >
                  {starting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                  {downloadSize > 0
                    ? `Download missing models (~${downloadSize.toFixed(0)} GB)`
                    : 'Nothing left to download'}
                </Button>
                {capabilities.text_encoder_optional && textEncoderRow && !textEncoderRow.downloaded && (
                  <label className="flex items-center gap-2 text-[11px] text-zinc-400">
                    <input
                      type="checkbox"
                      checked={skipTextEncoder}
                      onChange={e => setSkipTextEncoder(e.target.checked)}
                    />
                    Skip the local text encoder ({textEncoderRow.disk_size_gb?.toFixed(0)} GB) — use
                    cloud text encoding via the LTX API key
                  </label>
                )}
              </>
            )}
            {capabilities.gpu_verdict_level === 'none' && (
              <p className="flex items-start gap-1.5 text-[11px] text-amber-400">
                <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
                These models are unlikely to run on this machine's GPU — you can still download
                them, but generation will fail without sufficient VRAM.
              </p>
            )}
            {progress?.error && <p className="text-[11px] text-red-400">{progress.error}</p>}
            {note && <p className="text-[11px] text-zinc-500">{note}</p>}
          </div>
        )}

        {note && !(capabilities.execution_mode === 'local' && anyNotDownloaded) && (
          <p className="text-[11px] text-zinc-500">{note}</p>
        )}

        <p className="text-[11px] text-zinc-600 leading-relaxed">{capabilities.vram_note}</p>
        </>
        )}

        <FilmRenderSettingsCard />
      </div>
    </div>
  )
}
