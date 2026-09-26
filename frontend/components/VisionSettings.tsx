import { useCallback, useEffect, useState } from 'react'
import { Cpu, Eye, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { useAppSettings } from '../contexts/AppSettingsContext'
import { backendFetch } from '../lib/backend'
import { logger } from '../lib/logger'
import type { VisionSettings as VisionSettingsShape, VlmProvider } from '../types/settings'

interface ComponentStatus {
  name: string
  enabled: boolean
  available: boolean
  loaded: boolean
  model: string
  vram_class: 'S' | 'M' | 'L'
  estimated_mb: number
  note: string
}

interface VisionStatusPayload {
  vision: { mode: 'local' | 'sidecar' | 'fake'; device: string; components: ComponentStatus[] }
  vram: { free_mb: number | null; total_mb: number | null; loaded: string[]; ollama_model: string }
  cache: { entries: number; bytes: number }
  vlm: string
}

const FLORENCE_MODELS = [
  ['florence-2-large', 'Florence-2 large (0.77B · class M · best captions + grounding)'],
  ['florence-2-base', 'Florence-2 base (0.23B · class S · fast)'],
  ['promptgen-large-v2', 'PromptGen v2 large (tags + mixed caption)'],
  ['promptgen-base-v2', 'PromptGen v2 base'],
  ['cogflorence-large', 'CogFlorence 2.2 large (long captions)'],
  ['florence-2-flux-large', 'Florence-2 Flux large (Flux/T5-style captions)'],
] as const
const DEPTH_MODELS = [
  ['depth-anything-v2-small', 'Depth-Anything-V2 small (class S)'],
  ['depth-anything-v2-base', 'Depth-Anything-V2 base'],
] as const
const DINO_MODELS = [
  ['dinov2-small', 'DINOv2 small (class S)'],
  ['dinov2-base', 'DINOv2 base'],
] as const
const VLM_PROVIDERS: [VlmProvider, string][] = [
  ['off', 'Off — offline stack only (recommended on 12 GB)'],
  ['ollama', 'Ollama (qwen3-vl:4b if present, else qwen2.5vl:3b)'],
  ['openai_compatible', 'OpenAI-compatible endpoint'],
  ['director', 'Reuse the AI Director model'],
]

const COMPONENT_LABEL: Record<string, string> = {
  stats: 'Measured stats (always on)',
  florence: 'Florence-2 — captions, detection, grounding',
  clip: 'CLIP ViT-L/14 — style tags + embeddings',
  depth: 'Depth-Anything-V2 — depth maps',
  dino: 'DINOv2 — structural embeddings',
}

function mb(value: number | null): string {
  return value === null ? '—' : `${(value / 1024).toFixed(1)} GB`
}

/** Settings → Vision: the local vision stack, its VLM slot, VRAM and cache. */
export function VisionSettings() {
  const { settings, updateSettings } = useAppSettings()
  const vision = settings.vision
  const [status, setStatus] = useState<VisionStatusPayload | null>(null)
  const [statusError, setStatusError] = useState('')
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')

  const loadStatus = useCallback(async () => {
    try {
      const response = await backendFetch('/api/vision/status')
      if (!response.ok) throw new Error(`Status ${response.status}`)
      setStatus((await response.json()) as VisionStatusPayload)
      setStatusError('')
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => { void loadStatus() }, [loadStatus])

  const patch = useCallback(async (next: Partial<VisionSettingsShape>) => {
    const merged = { ...vision, ...next }
    updateSettings({ vision: merged })
    try {
      const response = await backendFetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vision: next }),
      })
      if (!response.ok) throw new Error(await response.text())
      void loadStatus()
    } catch (err) {
      logger.error(`Failed to save vision settings: ${err}`)
      setNote('Could not save: ' + (err instanceof Error ? err.message : String(err)))
    }
  }, [vision, updateSettings, loadStatus])

  const act = async (label: string, path: string, method: 'POST' | 'DELETE') => {
    setBusy(label)
    setNote('')
    try {
      const response = await backendFetch(path, { method })
      if (!response.ok) throw new Error(await response.text())
      const body = (await response.json()) as Record<string, unknown>
      setNote(label === 'unload' ? `Unloaded: ${(body.unloaded as string[] | undefined)?.join(', ') || 'nothing was loaded'}` : `Cache cleared (${String(body.removed ?? 0)} entries)`)
      await loadStatus()
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const toggle = (key: keyof VisionSettingsShape, label: string, description: string) => (
    <label className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
      <input
        type="checkbox"
        checked={Boolean(vision[key])}
        onChange={e => void patch({ [key]: e.target.checked } as Partial<VisionSettingsShape>)}
        className="mt-0.5 accent-violet-500"
        aria-label={label}
      />
      <span>
        <span className="block text-sm text-zinc-200">{label}</span>
        <span className="block text-xs text-zinc-500">{description}</span>
      </span>
    </label>
  )

  return (
    <div className="space-y-6" data-testid="vision-settings">
      <div>
        <h3 className="text-sm font-semibold text-white flex items-center gap-2"><Eye className="h-4 w-4 text-violet-400" /> Local vision stack</h3>
        <p className="text-xs text-zinc-500 mt-1 max-w-2xl">
          Reproduce and video analysis read images with these local models before any language model is asked.
          They are independent of the AI Director, load on demand, and are unloaded before every render so a 12 GB card never runs out.
          Weights are downloaded from the Model Library (AI Models → Vision).
        </p>
      </div>

      {toggle('enabled', 'Enable the local vision stack', 'Off = only the measured statistics (palette, contrast, edges) are used.')}

      <div className={`grid gap-3 sm:grid-cols-2 ${vision.enabled ? '' : 'pointer-events-none opacity-40'}`}>
        <div className="space-y-2">
          {toggle('florenceEnabled', 'Florence-2', 'Captions, object detection, phrase grounding.')}
          <select aria-label="Florence-2 model" value={vision.florenceModel} onChange={e => void patch({ florenceModel: e.target.value })} className="select-chip w-full">
            {FLORENCE_MODELS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </div>
        <div className="space-y-2">
          {toggle('clipEnabled', 'CLIP ViT-L/14', 'Style, medium and artist tags; image embeddings for scoring.')}
          <input aria-label="CLIP model id" value={vision.clipModel} onChange={e => void patch({ clipModel: e.target.value })} className="select-chip w-full" />
        </div>
        <div className="space-y-2">
          {toggle('depthEnabled', 'Depth estimation', 'Depth maps for the 3D storyboard and control video.')}
          <select aria-label="Depth model" value={vision.depthModel} onChange={e => void patch({ depthModel: e.target.value })} className="select-chip w-full">
            {DEPTH_MODELS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </div>
        <div className="space-y-2">
          {toggle('dinoEnabled', 'DINOv2', 'Structural similarity between a reference and its candidates.')}
          <select aria-label="DINOv2 model" value={vision.dinoModel} onChange={e => void patch({ dinoModel: e.target.value })} className="select-chip w-full">
            {DINO_MODELS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </div>
      </div>

      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Vision language model (optional)</h4>
        <p className="text-xs text-zinc-500">Adds narrative reads (what happens, mood). The 4070 preset keeps this off; a warm 6 GB VLM next to a 10 GB render is the classic out-of-memory.</p>
        <select aria-label="VLM provider" value={vision.vlmProvider} onChange={e => void patch({ vlmProvider: e.target.value as VlmProvider })} className="select-chip w-full">
          {VLM_PROVIDERS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
        {(vision.vlmProvider === 'ollama' || vision.vlmProvider === 'openai_compatible') && (
          <div className="grid gap-2 sm:grid-cols-3">
            <input aria-label="VLM base URL" value={vision.vlmBaseUrl} onChange={e => void patch({ vlmBaseUrl: e.target.value })} placeholder="http://127.0.0.1:11434" className="select-chip" />
            <input aria-label="VLM model" value={vision.vlmModel} onChange={e => void patch({ vlmModel: e.target.value })} placeholder="qwen3-vl:4b" className="select-chip" />
            <input aria-label="Ollama keep-alive" value={vision.vlmKeepAlive} onChange={e => void patch({ vlmKeepAlive: e.target.value })} placeholder="0" className="select-chip" title="Ollama keep_alive; 0 unloads the model right after each call" />
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Storage</h4>
        <input aria-label="Vision cache directory" value={vision.cacheDir} onChange={e => void patch({ cacheDir: e.target.value })} placeholder="default: <app data>/vision-cache" className="select-chip w-full" />
        <div className="flex gap-2 text-xs">
          <select aria-label="Vision mode" value={vision.mode} onChange={e => void patch({ mode: e.target.value as VisionSettingsShape['mode'] })} className="select-chip">
            <option value="auto">Auto (sidecar if TFG_VISION_URL answers, else in-process)</option>
            <option value="local">In-process</option>
            <option value="sidecar">Sidecar worker</option>
          </select>
          {vision.mode !== 'local' && <input aria-label="Sidecar URL" value={vision.sidecarUrl} onChange={e => void patch({ sidecarUrl: e.target.value })} className="select-chip flex-1" />}
        </div>
      </section>

      <section className="space-y-2" aria-label="Vision status">
        <div className="flex items-center gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 flex items-center gap-1"><Cpu className="h-3.5 w-3.5" /> Status</h4>
          <button onClick={() => void loadStatus()} className="btn-chip" aria-label="Refresh vision status"><RefreshCw className="h-3 w-3" /> Refresh</button>
          <button onClick={() => void act('unload', '/api/vision/unload', 'POST')} disabled={!!busy} className="btn-chip">{busy === 'unload' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />} Unload models</button>
          <button onClick={() => void act('cache', '/api/vision/cache', 'DELETE')} disabled={!!busy} className="btn-chip">Clear analysis cache</button>
        </div>
        {statusError && <p className="text-xs text-amber-300">Status unavailable: {statusError}</p>}
        {status && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-xs space-y-2">
            <p className="text-zinc-400">
              Mode <span className="text-zinc-200">{status.vision.mode}</span> · VRAM free <span className="text-zinc-200">{mb(status.vram.free_mb)}</span> of {mb(status.vram.total_mb)}
              {status.vram.loaded.length > 0 && <> · loaded: <span className="text-zinc-200">{status.vram.loaded.join(', ')}</span></>}
              {status.vram.ollama_model && <> · Ollama VLM: <span className="text-zinc-200">{status.vram.ollama_model}</span></>}
              {' · '}cache {status.cache.entries} entries
              {status.vlm && <> · VLM in use: <span className="text-zinc-200">{status.vlm}</span></>}
            </p>
            <ul className="grid gap-1 sm:grid-cols-2">
              {status.vision.components.map(component => (
                <li key={component.name} className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${!component.enabled ? 'bg-zinc-700' : component.loaded ? 'bg-emerald-400' : 'bg-zinc-500'}`} aria-hidden="true" />
                  <span className="text-zinc-300">{COMPONENT_LABEL[component.name] ?? component.name}</span>
                  <span className="text-zinc-600 ml-auto">{component.model}{component.estimated_mb ? ` · ${component.vram_class} · ${(component.estimated_mb / 1024).toFixed(1)} GB` : ''}{!component.enabled ? ' · off' : component.loaded ? ' · loaded' : ''}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {note && <p className="text-xs text-zinc-400" role="status">{note}</p>}
      </section>
    </div>
  )
}
