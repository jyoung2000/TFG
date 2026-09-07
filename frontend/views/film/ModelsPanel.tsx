import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Cloud, Cpu, Download, HardDrive, Loader2 } from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { backendFetch } from '../../lib/backend'
import { Button } from '../../components/ui/button'

interface DownloadProgress {
  status: string
  currentFile: string
  totalProgress: number
  downloadedBytes: number
  totalBytes: number
  speedMbps: number
  error: string | null
}

/**
 * VRAM-aware model manager: shows the detected GPU, every model the current
 * execution mode can use (with real on-disk sizes from the download specs),
 * whether it fits the GPU, and drives the existing /api/models/download
 * pipeline for anything not yet downloaded.
 */
export function ModelsPanel() {
  const { capabilities, refreshCapabilities } = useFilm()
  const [progress, setProgress] = useState<DownloadProgress | null>(null)
  const [starting, setStarting] = useState(false)
  const [note, setNote] = useState('')

  const downloading = progress?.status === 'downloading'

  // Poll download progress while a download runs.
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
        body: JSON.stringify({ skipTextEncoder: false }),
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
  }, [])

  if (!capabilities) {
    return (
      <div className="h-full flex items-center justify-center text-zinc-500">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    )
  }

  const anyNotDownloaded = capabilities.models.some(m => m.download_state === 'not_downloaded')

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

        {/* Model list */}
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
                <div className="text-xs font-medium text-zinc-200 truncate">{model.label}</div>
                <div className="text-[11px] text-zinc-500">
                  {model.modes.join(' + ')}
                  {model.disk_size_gb != null && ` · ${model.disk_size_gb.toFixed(0)} GB on disk`}
                  {model.estimated_min_vram_gb != null &&
                    ` · needs ~${model.estimated_min_vram_gb.toFixed(0)} GB VRAM`}
                  {model.supported_resolutions.length > 0 &&
                    ` · up to ${model.supported_resolutions[model.supported_resolutions.length - 1]}`}
                </div>
              </div>
              {model.fits_gpu === false && (
                <span
                  className="flex items-center gap-1 text-[10px] text-amber-400"
                  title="Estimated VRAM need exceeds the detected GPU"
                >
                  <AlertTriangle className="h-3 w-3" /> May not fit GPU
                </span>
              )}
              {model.fits_gpu === true && (
                <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                  <CheckCircle2 className="h-3 w-3" /> Fits GPU
                </span>
              )}
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                  model.download_state === 'downloaded'
                    ? 'bg-emerald-900/60 text-emerald-300'
                    : model.download_state === 'not_downloaded'
                      ? 'bg-zinc-800 text-zinc-400'
                      : 'bg-sky-900/60 text-sky-300'
                }`}
              >
                {model.download_state === 'downloaded'
                  ? 'Downloaded'
                  : model.download_state === 'not_downloaded'
                    ? 'Not downloaded'
                    : model.download_state === 'managed_by_wangp'
                      ? 'Managed by WanGP'
                      : 'Cloud'}
              </span>
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
                  Downloading {progress.currentFile} · {progress.speedMbps} MB/s
                </div>
                <div className="h-1.5 rounded bg-zinc-800 overflow-hidden">
                  <div
                    className="h-full bg-violet-600 transition-all"
                    style={{ width: `${progress.totalProgress}%` }}
                  />
                </div>
              </>
            ) : (
              <Button size="sm" onClick={() => void startDownload()} disabled={starting} className="gap-1.5">
                {starting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                Download required models
              </Button>
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
