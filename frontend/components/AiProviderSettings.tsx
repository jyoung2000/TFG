import { useCallback, useState } from 'react'
import { Check, ExternalLink, KeyRound, Loader2, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'
import { useAppSettings, type ClearableKeyProvider } from '../contexts/AppSettingsContext'
import { filmApi } from '../lib/film-api'
import type { OpenRouterModelInfo } from '../types/film'
import { MEDIA_PROVIDER_LABELS, PROVIDER_DOC_URLS, type MediaProviderId } from '../types/models'

const inputClass =
  'w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600'

/**
 * One hosted provider: a write-only key, the model id it should use, and a
 * refresh that asks the provider itself which models the key can reach — the
 * app never ships a fixed list that could go stale.
 */
function TextProviderCard({
  provider,
  title,
  blurb,
  keyProvider,
  hasKey,
  model,
  placeholder,
  docsUrl,
  onModelChange,
}: {
  provider: string
  title: string
  blurb: string
  keyProvider: ClearableKeyProvider
  hasKey: boolean
  model: string
  placeholder: string
  docsUrl: string
  onModelChange: (value: string) => void
}) {
  const { saveApiKey, clearApiKey } = useAppSettings()
  const [keyInput, setKeyInput] = useState('')
  const [busy, setBusy] = useState<'save' | 'clear' | 'models' | null>(null)
  const [models, setModels] = useState<OpenRouterModelInfo[]>([])
  const [note, setNote] = useState('')

  const save = useCallback(async () => {
    const trimmed = keyInput.trim()
    if (!trimmed) return
    setBusy('save')
    setNote('')
    try {
      await saveApiKey(keyProvider, trimmed)
      setKeyInput('')
      setNote('Key saved')
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [keyInput, keyProvider, saveApiKey])

  const loadModels = useCallback(async () => {
    setBusy('models')
    setNote('')
    try {
      const result = await filmApi.directorModels(provider, true)
      setModels(result.models)
      setNote(result.models.length ? `${result.models.length} models available` : 'The provider returned no models')
    } catch (e) {
      setNote(`Could not load models: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [provider])

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <KeyRound className="h-3.5 w-3.5 text-zinc-500" />
        <span className="text-xs font-semibold text-white">{title}</span>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded ${hasKey ? 'bg-emerald-500/10 text-emerald-300' : 'bg-zinc-800 text-zinc-500'}`}
        >
          {hasKey ? 'connected' : 'no key'}
        </span>
        <a
          href={docsUrl}
          target="_blank"
          rel="noreferrer"
          className="ml-auto flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300"
        >
          models <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      <p className="text-[10px] text-zinc-600 leading-snug">{blurb}</p>
      <div className="flex gap-2">
        <input
          type="password"
          autoComplete="off"
          value={keyInput}
          onChange={e => setKeyInput(e.target.value)}
          onKeyDown={e => {
            e.stopPropagation()
            if (e.key === 'Enter') void save()
          }}
          placeholder={hasKey ? 'Key stored — enter a new one to replace' : 'Paste the API key'}
          aria-label={`${title} API key`}
          className={inputClass}
        />
        <button
          onClick={() => void save()}
          disabled={!keyInput.trim() || busy !== null}
          className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 whitespace-nowrap"
        >
          {busy === 'save' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Save'}
        </button>
        {hasKey && (
          <button
            onClick={() => {
              setBusy('clear')
              void clearApiKey(keyProvider).finally(() => setBusy(null))
            }}
            disabled={busy !== null}
            aria-label={`Remove the ${title} key`}
            className="flex items-center gap-1 text-xs text-zinc-400 hover:text-red-300 px-2 py-1.5 rounded bg-zinc-800 border border-zinc-700"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>
      <div className="flex gap-2 items-center">
        <input
          list={`${provider}-models`}
          value={model}
          onChange={e => onModelChange(e.target.value)}
          placeholder={placeholder}
          aria-label={`${title} model id`}
          className={`${inputClass} font-mono`}
        />
        <datalist id={`${provider}-models`}>
          {models.map(m => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </datalist>
        <button
          onClick={() => void loadModels()}
          disabled={!hasKey || busy !== null}
          className="flex items-center gap-1 px-2 py-1.5 rounded bg-zinc-800 border border-zinc-700 text-[11px] text-zinc-300 hover:bg-zinc-700 disabled:opacity-40 whitespace-nowrap"
          title="Ask the provider which models this key can use"
        >
          {busy === 'models' ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          Models
        </button>
      </div>
      {note && <div className="text-[11px] text-zinc-400">{note}</div>}
    </div>
  )
}

/** Key + default model for a hosted image/video provider. */
function MediaProviderCard({
  provider,
  hasKey,
  keyProvider,
}: {
  provider: MediaProviderId
  hasKey: boolean
  keyProvider: ClearableKeyProvider
}) {
  const { saveApiKey, clearApiKey } = useAppSettings()
  const [keyInput, setKeyInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')

  const save = useCallback(async () => {
    const trimmed = keyInput.trim()
    if (!trimmed) return
    setBusy(true)
    setNote('')
    try {
      await saveApiKey(keyProvider, trimmed)
      setKeyInput('')
      setNote('Key saved')
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [keyInput, keyProvider, saveApiKey])

  return (
    <div className="flex items-center gap-2">
      <span className="w-24 text-[11px] text-zinc-400 shrink-0">{MEDIA_PROVIDER_LABELS[provider]}</span>
      <input
        type="password"
        autoComplete="off"
        value={keyInput}
        onChange={e => setKeyInput(e.target.value)}
        onKeyDown={e => {
          e.stopPropagation()
          if (e.key === 'Enter') void save()
        }}
        placeholder={hasKey ? 'Key stored — enter a new one to replace' : `${provider} API key`}
        aria-label={`${provider} API key`}
        className={inputClass}
      />
      <button
        onClick={() => void save()}
        disabled={!keyInput.trim() || busy}
        className="px-2.5 py-1.5 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500"
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Save'}
      </button>
      {hasKey && (
        <button
          onClick={() => void clearApiKey(keyProvider)}
          aria-label={`Remove the ${provider} key`}
          className="p-1.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-red-300"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      )}
      <a
        href={PROVIDER_DOC_URLS[provider]}
        target="_blank"
        rel="noreferrer"
        className="text-[10px] text-zinc-500 hover:text-zinc-300 whitespace-nowrap"
      >
        catalog
      </a>
      {note && <span className="text-[10px] text-zinc-500 truncate">{note}</span>}
    </div>
  )
}

/**
 * Everything a film needs to know about providers: which text model directs,
 * and where images and video are generated. Keys are write-only — the backend
 * stores them and only ever returns a "connected" flag.
 */
export function AiProviderSettings() {
  const { settings, updateSettings } = useAppSettings()

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-2">
        <TextProviderCard
          provider="anthropic"
          title="Claude (Anthropic)"
          blurb="Strong tool use — a good default for the AI Director's structured edits."
          keyProvider="anthropic"
          hasKey={settings.hasAnthropicApiKey}
          model={settings.anthropicModel}
          placeholder="claude-sonnet-5 (default)"
          docsUrl={PROVIDER_DOC_URLS.anthropic}
          onModelChange={value => updateSettings({ anthropicModel: value })}
        />
        <TextProviderCard
          provider="xai"
          title="Grok (xAI)"
          blurb="OpenAI-compatible endpoint at api.x.ai."
          keyProvider="xai"
          hasKey={settings.hasXaiApiKey}
          model={settings.xaiModel}
          placeholder="grok-4 (default)"
          docsUrl={PROVIDER_DOC_URLS.xai}
          onModelChange={value => updateSettings({ xaiModel: value })}
        />
        <TextProviderCard
          provider="gemini"
          title="Gemini (Google)"
          blurb="Also used for the optional visual continuity review."
          keyProvider="gemini"
          hasKey={settings.hasGeminiApiKey}
          model={settings.geminiModel}
          placeholder="gemini-2.0-flash (default)"
          docsUrl={PROVIDER_DOC_URLS.gemini}
          onModelChange={value => updateSettings({ geminiModel: value })}
        />
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 space-y-2">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-3.5 w-3.5 text-violet-400" />
          <span className="text-xs font-semibold text-white">Image &amp; video generation</span>
        </div>
        <p className="text-[10px] text-zinc-600 leading-snug">
          Where shots and reference images are rendered. <strong className="text-zinc-400">This computer</strong> needs
          no key and works with no internet at all; the hosted options need a key and a model id from that provider's
          catalog. Films can override this per project in the Model Library.
        </p>
        <div className="grid grid-cols-2 gap-1.5">
          {(Object.keys(MEDIA_PROVIDER_LABELS) as MediaProviderId[]).map(provider => (
            <button
              key={provider}
              onClick={() => updateSettings({ mediaProvider: provider })}
              aria-pressed={settings.mediaProvider === provider}
              className={`flex items-center gap-1.5 px-2 py-1.5 rounded text-xs text-left ${
                settings.mediaProvider === provider ? 'bg-violet-600/80 text-white' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              {settings.mediaProvider === provider && <Check className="h-3 w-3 shrink-0" />}
              {MEDIA_PROVIDER_LABELS[provider]}
            </button>
          ))}
        </div>
        {settings.mediaProvider !== 'local' && (
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-[11px] text-zinc-400">
              Default video model
              <input
                value={settings.defaultVideoModel}
                onChange={e => updateSettings({ defaultVideoModel: e.target.value })}
                placeholder="provider model id"
                aria-label="Default video model id"
                className={`${inputClass} mt-0.5 font-mono`}
              />
            </label>
            <label className="block text-[11px] text-zinc-400">
              Default image model
              <input
                value={settings.defaultImageModel}
                onChange={e => updateSettings({ defaultImageModel: e.target.value })}
                placeholder="provider model id"
                aria-label="Default image model id"
                className={`${inputClass} mt-0.5 font-mono`}
              />
            </label>
          </div>
        )}
        <div className="space-y-1.5 pt-1">
          <MediaProviderCard provider="fal" hasKey={settings.hasFalApiKey} keyProvider="fal" />
          <MediaProviderCard provider="wavespeed" hasKey={settings.hasWavespeedApiKey} keyProvider="wavespeed" />
          <MediaProviderCard provider="replicate" hasKey={settings.hasReplicateApiKey} keyProvider="replicate" />
        </div>
      </div>
    </div>
  )
}
