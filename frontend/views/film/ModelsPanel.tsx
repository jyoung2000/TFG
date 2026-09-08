import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Cloud,
  Cpu,
  Download,
  HardDrive,
  Info,
  Loader2,
  XCircle,
} from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { backendFetch } from '../../lib/backend'
import { Button } from '../../components/ui/button'
import type { FilmModelCapability } from '../../types/film'

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

function StateChip({ model }: { model: FilmModelCapability }) {
  const map: Record<FilmModelCapability['download_state'], { label: string; className: string }> = {
    downloaded: { label: 'Downloaded', className: 'bg-emerald-900/60 text-emerald-300' },
    not_downloaded: { label: 'Not downloaded', className: 'bg-zinc-800 text-zinc-400' },
    managed_by_wangp: { label: 'Managed by WanGP', className: 'bg-sky-900/60 text-sky-300' },
    cloud: { label: 'Cloud', className: 'bg-sky-900/60 text-sky-300' },
    not_configured: { label: 'Needs WanGP setup', className: 'bg-amber-950/70 text-amber-300' },
  }
  const meta = map[model.download_state]
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${meta.className}`}>
      {meta.label}
    </span>
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
  const [progress, setProgress] = useState<DownloadProgress | null>(null)
  const [starting, setStarting] = useState(false)
  const [skipTextEncoder, setSkipTextEncoder] = useState(false)
  const [skipDefaultApplied, setSkipDefaultApplied] = useState(false)
  const [note, setNote] = useState('')

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
                  {!model.required && model.download_state !== 'not_configured' && (
                    <span className="ml-1.5 text-[10px] text-zinc-600">(optional)</span>
                  )}
                </div>
                <div className="text-[11px] text-zinc-500">
                  {model.modes.join(' + ')}
                  {model.disk_size_gb != null && ` · ${model.disk_size_gb.toFixed(0)} GB on disk`}
                  {model.estimated_min_vram_gb != null &&
                    ` · needs ~${model.estimated_min_vram_gb.toFixed(0)} GB VRAM`}
                  {model.supported_resolutions.length > 0 &&
                    ` · up to ${model.supported_resolutions[model.supported_resolutions.length - 1]}`}
                </div>
                {model.download_state === 'not_configured' && (
                  <div className="text-[10px] text-amber-400/80 mt-0.5">
                    Runs LTX on 6 GB+ GPUs. Set WANGP_ROOT to a WanGP checkout — see the README's
                    WanGP quick start.
                  </div>
                )}
              </div>
              <FitBadge model={model} />
              <StateChip model={model} />
            </div>
          ))}
        </div>

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

        <p className="text-[11px] text-zinc-600 leading-relaxed">{capabilities.vram_note}</p>
      </div>
    </div>
  )
}
