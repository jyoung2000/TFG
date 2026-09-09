import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Cloud, HardDrive, Image as ImageIcon, Loader2, Type, Video } from 'lucide-react'
import { useAppSettings, type AppSettings, type DirectorProviderSetting } from '../../contexts/AppSettingsContext'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi } from '../../lib/film-api'
import { modelLibraryApi } from '../../lib/model-library-api'
import {
  MEDIA_PROVIDER_LABELS,
  TEXT_PROVIDER_LABELS,
  type LibraryModel,
  type LibraryTask,
  type MediaProviderId,
  type TextProviderId,
} from '../../types/models'

/**
 * The model pickers that sit in the chat bar: which model directs, and which
 * models make the pictures. Changing one here changes what the next
 * generation actually uses — text goes to app settings, image/video to the
 * open film so different projects can differ.
 */
export function ChatModelPickers() {
  const [open, setOpen] = useState<LibraryTask | null>(null)
  const { settings } = useAppSettings()
  const { film } = useFilm()
  const wrapper = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (wrapper.current && !wrapper.current.contains(event.target as Node)) setOpen(null)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(null)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const mediaProvider = (film?.settings.media_provider || settings.mediaProvider || 'local') as MediaProviderId
  const videoModel =
    mediaProvider === 'local'
      ? film?.settings.default_model || 'local model'
      : film?.settings.video_model || settings.defaultVideoModel || 'not set'
  const imageModel =
    mediaProvider === 'local'
      ? 'local model'
      : film?.settings.image_model || settings.defaultImageModel || 'not set'
  const directorProvider = settings.directorProvider
  const directorModel =
    directorProvider === 'openrouter'
      ? settings.openrouterModels.director || settings.openrouterModels.defaultModel
      : directorProvider === 'anthropic'
        ? settings.anthropicModel || 'claude-sonnet-5'
        : directorProvider === 'xai'
          ? settings.xaiModel || 'grok-4'
          : directorProvider === 'gemini'
            ? settings.geminiModel || 'gemini-2.0-flash'
            : directorProvider === 'openai_compatible'
              ? settings.openaiCompatibleModel || 'not set'
              : 'auto'

  return (
    <div ref={wrapper} className="relative flex items-center gap-1 text-[10px]">
      <Chip
        icon={<Type className="h-3 w-3" />}
        label="Director"
        value={directorModel}
        active={open === 'text'}
        onClick={() => setOpen(open === 'text' ? null : 'text')}
      />
      <Chip
        icon={<Video className="h-3 w-3" />}
        label="Video"
        value={videoModel}
        hosted={mediaProvider !== 'local'}
        active={open === 'video'}
        onClick={() => setOpen(open === 'video' ? null : 'video')}
      />
      <Chip
        icon={<ImageIcon className="h-3 w-3" />}
        label="Image"
        value={imageModel}
        hosted={mediaProvider !== 'local'}
        active={open === 'image'}
        onClick={() => setOpen(open === 'image' ? null : 'image')}
      />
      {open && (
        <div className="absolute bottom-full left-0 mb-1.5 z-40 w-[26rem] rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl p-3">
          {open === 'text' ? <DirectorPicker onDone={() => setOpen(null)} /> : <MediaPicker task={open} onDone={() => setOpen(null)} />}
        </div>
      )}
    </div>
  )
}

function Chip({
  icon,
  label,
  value,
  hosted,
  active,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  value: string
  hosted?: boolean
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      aria-expanded={active}
      title={`${label} model: ${value} — click to change`}
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded border max-w-[13rem] ${
        active ? 'border-violet-600 bg-violet-950/40 text-violet-200' : 'border-zinc-800 bg-zinc-900 text-zinc-400 hover:text-zinc-200'
      }`}
    >
      {icon}
      <span className="text-zinc-600">{label}</span>
      <span className="truncate font-mono">{value}</span>
      {hosted !== undefined && (hosted ? <Cloud className="h-2.5 w-2.5 shrink-0" /> : <HardDrive className="h-2.5 w-2.5 shrink-0" />)}
      <ChevronDown className="h-3 w-3 shrink-0" />
    </button>
  )
}

/** Provider + model for the AI Director's text model. */
function DirectorPicker({ onDone }: { onDone: () => void }) {
  const { settings, updateSettings } = useAppSettings()
  const [models, setModels] = useState<LibraryModel[]>([])
  const [loading, setLoading] = useState(true)
  const [note, setNote] = useState('')

  useEffect(() => {
    let cancelled = false
    void modelLibraryApi
      .search({ task: 'text', limit: 300 })
      .then(result => {
        if (!cancelled) setModels(result.models)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const provider = settings.directorProvider
  const configured: Record<string, boolean> = {
    openrouter: settings.hasOpenrouterApiKey,
    anthropic: settings.hasAnthropicApiKey,
    xai: settings.hasXaiApiKey,
    gemini: settings.hasGeminiApiKey,
    openai_compatible: Boolean(settings.openaiCompatibleBaseUrl && settings.openaiCompatibleModel),
  }

  const setModel = useCallback(
    (target: TextProviderId, value: string) => {
      const patch: Partial<AppSettings> = { directorProvider: target }
      if (target === 'openrouter') patch.openrouterModels = { ...settings.openrouterModels, director: value }
      if (target === 'anthropic') patch.anthropicModel = value
      if (target === 'xai') patch.xaiModel = value
      if (target === 'gemini') patch.geminiModel = value
      if (target === 'openai_compatible') patch.openaiCompatibleModel = value
      updateSettings(patch)
      void modelLibraryApi.remember(target === 'openai_compatible' ? 'openai_compatible' : target, value).catch(() => {})
      setNote(`Director now uses ${value}`)
    },
    [settings.openrouterModels, updateSettings],
  )

  const current = (target: TextProviderId): string =>
    target === 'openrouter'
      ? settings.openrouterModels.director || settings.openrouterModels.defaultModel
      : target === 'anthropic'
        ? settings.anthropicModel
        : target === 'xai'
          ? settings.xaiModel
          : target === 'gemini'
            ? settings.geminiModel
            : settings.openaiCompatibleModel

  return (
    <div className="space-y-2">
      <div className="text-[11px] font-semibold text-white">AI Director model</div>
      <div className="grid grid-cols-3 gap-1">
        {(['auto', ...(Object.keys(TEXT_PROVIDER_LABELS) as TextProviderId[])] as DirectorProviderSetting[]).map(id => (
          <button
            key={id}
            onClick={() => updateSettings({ directorProvider: id })}
            aria-pressed={provider === id}
            className={`flex items-center gap-1 px-1.5 py-1 rounded text-[10px] ${
              provider === id ? 'bg-violet-600/80 text-white' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
            }`}
          >
            {provider === id && <Check className="h-2.5 w-2.5" />}
            <span className="truncate">{id === 'auto' ? 'Auto' : TEXT_PROVIDER_LABELS[id as TextProviderId]}</span>
            {id !== 'auto' && !configured[id] && <span className="text-amber-400">·no key</span>}
          </button>
        ))}
      </div>
      {provider !== 'auto' && (
        <label className="block text-[11px] text-zinc-400">
          Model id
          <input
            list="director-model-options"
            defaultValue={current(provider as TextProviderId)}
            onBlur={e => setModel(provider as TextProviderId, e.target.value.trim())}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                setModel(provider as TextProviderId, (e.target as HTMLInputElement).value.trim())
                onDone()
              }
            }}
            placeholder="pick or type a model id"
            aria-label="Director model id"
            className="mt-0.5 w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-[11px] text-zinc-200 font-mono"
          />
        </label>
      )}
      <datalist id="director-model-options">
        {models
          .filter(m => provider === 'auto' || m.provider === provider || (provider === 'openai_compatible' && m.provider === 'ollama'))
          .map(m => (
            <option key={`${m.provider}:${m.id}`} value={m.id}>
              {m.provider} · {m.name}
            </option>
          ))}
      </datalist>
      <div className="max-h-40 overflow-y-auto space-y-0.5">
        {loading && <Loader2 className="h-3 w-3 animate-spin text-zinc-500" />}
        {models.slice(0, 40).map(model => (
          <button
            key={`${model.provider}:${model.id}`}
            onClick={() => {
              const target = (model.provider === 'ollama' ? 'openai_compatible' : model.provider) as TextProviderId
              if (!TEXT_PROVIDER_LABELS[target]) return
              setModel(target, model.id)
            }}
            className="w-full flex items-center gap-1.5 px-1.5 py-1 rounded hover:bg-zinc-800 text-left"
          >
            {model.source === 'local' ? <HardDrive className="h-3 w-3 text-emerald-400 shrink-0" /> : <Cloud className="h-3 w-3 text-zinc-500 shrink-0" />}
            <span className="flex-1 truncate text-[11px] text-zinc-300 font-mono">{model.id}</span>
            <span className="text-[10px] text-zinc-600">{model.provider}</span>
          </button>
        ))}
        {!loading && models.length === 0 && (
          <div className="text-[10px] text-zinc-500">No text models yet — add a provider key or connect a local server.</div>
        )}
      </div>
      {note && <div className="text-[10px] text-emerald-300">{note}</div>}
    </div>
  )
}

/** Provider + model for image or video generation in this film. */
function MediaPicker({ task, onDone }: { task: 'image' | 'video'; onDone: () => void }) {
  const { settings, updateSettings } = useAppSettings()
  const { film, refresh } = useFilm()
  const [models, setModels] = useState<LibraryModel[]>([])
  const [loading, setLoading] = useState(true)
  const [note, setNote] = useState('')

  useEffect(() => {
    let cancelled = false
    void modelLibraryApi
      .search({ task, limit: 300 })
      .then(result => {
        if (!cancelled) setModels(result.models)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [task])

  const provider = (film?.settings.media_provider || settings.mediaProvider || 'local') as MediaProviderId

  const apply = useCallback(
    async (nextProvider: MediaProviderId, modelId: string) => {
      setNote('')
      try {
        if (film) {
          await filmApi.updateSettings(film.id, {
            ...film.settings,
            media_provider: nextProvider,
            ...(task === 'video' ? { video_model: nextProvider === 'local' ? '' : modelId } : { image_model: nextProvider === 'local' ? '' : modelId }),
            ...(task === 'video' && nextProvider === 'local' && modelId ? { default_model: modelId } : {}),
          })
          await refresh()
        }
        updateSettings({
          mediaProvider: nextProvider,
          ...(task === 'video' ? { defaultVideoModel: nextProvider === 'local' ? '' : modelId } : { defaultImageModel: nextProvider === 'local' ? '' : modelId }),
        })
        if (modelId) void modelLibraryApi.remember(nextProvider, modelId).catch(() => {})
        setNote(nextProvider === 'local' ? 'Generating on this computer' : `Using ${modelId} on ${nextProvider}`)
      } catch (e) {
        setNote(e instanceof Error ? e.message : String(e))
      }
    },
    [film, refresh, task, updateSettings],
  )

  const currentModel =
    task === 'video'
      ? film?.settings.video_model || settings.defaultVideoModel
      : film?.settings.image_model || settings.defaultImageModel

  const keyed: Record<string, boolean> = {
    local: true,
    fal: settings.hasFalApiKey,
    wavespeed: settings.hasWavespeedApiKey,
    replicate: settings.hasReplicateApiKey,
  }

  return (
    <div className="space-y-2">
      <div className="text-[11px] font-semibold text-white">{task === 'video' ? 'Video' : 'Image'} model for this film</div>
      <div className="grid grid-cols-2 gap-1">
        {(Object.keys(MEDIA_PROVIDER_LABELS) as MediaProviderId[]).map(id => (
          <button
            key={id}
            onClick={() => void apply(id, id === provider ? currentModel : '')}
            aria-pressed={provider === id}
            className={`flex items-center gap-1 px-1.5 py-1 rounded text-[10px] ${
              provider === id ? 'bg-violet-600/80 text-white' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
            }`}
          >
            {provider === id && <Check className="h-2.5 w-2.5" />}
            <span className="truncate">{MEDIA_PROVIDER_LABELS[id]}</span>
            {!keyed[id] && <span className="text-amber-400">·no key</span>}
          </button>
        ))}
      </div>
      <div className="max-h-40 overflow-y-auto space-y-0.5">
        {loading && <Loader2 className="h-3 w-3 animate-spin text-zinc-500" />}
        {models
          .filter(model => (provider === 'local' ? model.source === 'local' : model.provider === provider))
          .slice(0, 40)
          .map(model => (
            <button
              key={`${model.provider}:${model.id}`}
              onClick={() => void apply(model.source === 'local' ? 'local' : (model.provider as MediaProviderId), model.id)}
              className="w-full flex items-center gap-1.5 px-1.5 py-1 rounded hover:bg-zinc-800 text-left"
            >
              {model.source === 'local' ? <HardDrive className="h-3 w-3 text-emerald-400 shrink-0" /> : <Cloud className="h-3 w-3 text-zinc-500 shrink-0" />}
              <span className="flex-1 truncate text-[11px] text-zinc-300 font-mono">{model.id}</span>
              {model.fits_gpu === false && <span className="text-[10px] text-red-400">VRAM</span>}
              {!model.installed && model.source === 'local' && <span className="text-[10px] text-zinc-600">not installed</span>}
            </button>
          ))}
      </div>
      {provider !== 'local' && (
        <label className="block text-[11px] text-zinc-400">
          Model id
          <input
            defaultValue={currentModel}
            onBlur={e => void apply(provider, e.target.value.trim())}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                void apply(provider, (e.target as HTMLInputElement).value.trim())
                onDone()
              }
            }}
            placeholder="paste a model id from the provider's catalog"
            aria-label={`${task} model id`}
            className="mt-0.5 w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-[11px] text-zinc-200 font-mono"
          />
        </label>
      )}
      {note && <div className="text-[10px] text-emerald-300">{note}</div>}
      <div className="text-[10px] text-zinc-600">
        Download local models or browse every provider in Storyboard → Models → Model Library.
      </div>
    </div>
  )
}
