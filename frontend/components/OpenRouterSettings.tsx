import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, Check, KeyRound, Loader2, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'
import { useAppSettings, type DirectorProviderSetting, type OpenRouterRoleModels } from '../contexts/AppSettingsContext'
import { filmApi } from '../lib/film-api'
import { DIRECTOR_ROLES, type OpenRouterModelInfo, type OpenRouterValidation } from '../types/film'

const PROVIDER_OPTIONS: { id: DirectorProviderSetting; label: string; hint: string }[] = [
  { id: 'auto', label: 'Auto', hint: 'OpenRouter when a key exists, then Gemini, then a local endpoint' },
  { id: 'openrouter', label: 'OpenRouter', hint: 'Any model on openrouter.ai' },
  { id: 'anthropic', label: 'Claude', hint: 'Anthropic API key' },
  { id: 'xai', label: 'Grok', hint: 'xAI API key' },
  { id: 'gemini', label: 'Gemini', hint: 'Google AI Studio key' },
  { id: 'openai_compatible', label: 'Local / OpenAI-compatible', hint: 'LM Studio, vLLM, Ollama (OpenAI API), any /v1 endpoint' },
]

/**
 * OpenRouter is the first-class AI Director provider. The key is stored by the
 * backend in its settings file (never returned to this renderer — only a
 * `hasOpenrouterApiKey` flag comes back) or read from OPENROUTER_API_KEY.
 */
export function OpenRouterSettings() {
  const { settings, updateSettings, saveOpenrouterApiKey, clearApiKey } = useAppSettings()
  const [keyInput, setKeyInput] = useState('')
  const [busy, setBusy] = useState<'save' | 'validate' | 'clear' | 'models' | null>(null)
  const [validation, setValidation] = useState<OpenRouterValidation | null>(null)
  const [error, setError] = useState('')
  const [models, setModels] = useState<OpenRouterModelInfo[]>([])
  const [modelsNote, setModelsNote] = useState('')
  const [filter, setFilter] = useState('')

  const loadModels = useCallback(
    async (refresh: boolean) => {
      setBusy('models')
      setModelsNote('')
      try {
        const result = await filmApi.openrouterModels(refresh)
        setModels(result.models)
        setModelsNote(`${result.models.length} models${result.cached ? ' (cached)' : ''}`)
      } catch (e) {
        setModelsNote(`Could not load models: ${e instanceof Error ? e.message : e}`)
      } finally {
        setBusy(null)
      }
    },
    [],
  )

  useEffect(() => {
    if (settings.hasOpenrouterApiKey && models.length === 0) void loadModels(false)
  }, [settings.hasOpenrouterApiKey, models.length, loadModels])

  const save = useCallback(async () => {
    const trimmed = keyInput.trim()
    if (!trimmed) return
    setBusy('save')
    setError('')
    setValidation(null)
    try {
      await saveOpenrouterApiKey(trimmed)
      setKeyInput('')
      const result = await filmApi.validateOpenrouterKey()
      setValidation(result)
      if (result.valid) void loadModels(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [keyInput, saveOpenrouterApiKey, loadModels])

  const validate = useCallback(async () => {
    setBusy('validate')
    setError('')
    try {
      setValidation(await filmApi.validateOpenrouterKey())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [])

  const clear = useCallback(async () => {
    if (!window.confirm('Remove the stored OpenRouter API key?')) return
    setBusy('clear')
    setError('')
    try {
      await clearApiKey('openrouter')
      setValidation(null)
      setModels([])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [clearApiKey])

  const setRoleModel = useCallback(
    (role: keyof OpenRouterRoleModels, value: string) => {
      updateSettings(prev => ({
        ...prev,
        openrouterModels: { ...prev.openrouterModels, [role]: value },
      }))
    },
    [updateSettings],
  )

  const filteredModels = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const list = needle ? models.filter(m => m.id.toLowerCase().includes(needle) || m.name.toLowerCase().includes(needle)) : models
    return list.slice(0, 400)
  }, [models, filter])

  const keySource = settings.openrouterKeySource
  const inputClass =
    'w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'

  return (
    <div className="space-y-4 pt-4 border-t border-zinc-800">
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 text-emerald-400" />
        <h3 className="text-sm font-semibold text-white">OpenRouter</h3>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300">AI Director</span>
      </div>
      <p className="text-xs text-zinc-500 leading-relaxed">
        Powers the AI Director, Build Film with AI, AI Storyboard, and prompt refinement with any model on
        openrouter.ai. The key is kept by the local backend in its settings file and is never sent to the
        renderer or stored in project files; you can also set the <code className="text-zinc-300">OPENROUTER_API_KEY</code>{' '}
        environment variable instead.
      </p>

      <div className="bg-zinc-800/50 rounded-lg p-4 space-y-3">
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
            placeholder={settings.hasOpenrouterApiKey ? 'Enter new key to replace…' : 'sk-or-v1-…'}
            aria-label="OpenRouter API key"
            className={inputClass}
          />
          <button
            onClick={() => void save()}
            disabled={!keyInput.trim() || busy !== null}
            className="px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
          >
            {busy === 'save' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Save Key'}
          </button>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <div
            className={`text-xs px-2 py-1 rounded inline-flex items-center gap-1.5 ${
              settings.hasOpenrouterApiKey ? 'bg-green-500/10 text-green-400' : 'bg-amber-500/10 text-amber-400'
            }`}
          >
            {settings.hasOpenrouterApiKey ? (
              <>
                <Check className="h-3 w-3" />
                {keySource === 'env' ? 'Key from OPENROUTER_API_KEY' : 'Key configured'}
              </>
            ) : (
              <>
                <AlertCircle className="h-3 w-3" />
                No key
              </>
            )}
          </div>
          {settings.hasOpenrouterApiKey && (
            <>
              <button
                onClick={() => void validate()}
                disabled={busy !== null}
                className="flex items-center gap-1 text-xs text-zinc-300 hover:text-white px-2 py-1 rounded bg-zinc-800 border border-zinc-700"
              >
                {busy === 'validate' ? <Loader2 className="h-3 w-3 animate-spin" /> : <ShieldCheck className="h-3 w-3" />}
                Test key
              </button>
              {keySource === 'settings' && (
                <button
                  onClick={() => void clear()}
                  disabled={busy !== null}
                  className="flex items-center gap-1 text-xs text-zinc-400 hover:text-red-300 px-2 py-1 rounded bg-zinc-800 border border-zinc-700"
                >
                  <Trash2 className="h-3 w-3" /> Remove
                </button>
              )}
            </>
          )}
          <a
            href="https://openrouter.ai/keys"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2 ml-auto"
            onClick={e => e.stopPropagation()}
          >
            Get OpenRouter key →
          </a>
        </div>

        {validation && (
          <div className={`text-xs ${validation.valid ? 'text-emerald-300' : 'text-red-300'}`}>
            {validation.valid
              ? `✓ ${validation.message}${validation.label ? ` · "${validation.label}"` : ''}${
                  validation.limit != null ? ` · $${(validation.usage ?? 0).toFixed(2)} / $${validation.limit.toFixed(2)} used` : ''
                }${validation.is_free_tier ? ' · free tier' : ''}`
              : `✗ ${validation.message}`}
          </div>
        )}
        {error && <div className="text-xs text-red-300">{error}</div>}
      </div>

      {/* Provider selection */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-zinc-300">AI Director provider</div>
        <div className="grid grid-cols-2 gap-2">
          {PROVIDER_OPTIONS.map(option => {
            const active = settings.directorProvider === option.id
            return (
              <button
                key={option.id}
                onClick={() => updateSettings({ directorProvider: option.id })}
                className={`text-left rounded-lg border-2 p-2.5 transition-colors ${
                  active ? 'border-blue-500 bg-zinc-800/60' : 'border-transparent bg-zinc-800/40 hover:border-zinc-600'
                }`}
              >
                <div className="text-xs font-medium text-white">{option.label}</div>
                <div className="text-[10px] text-zinc-500 leading-snug mt-0.5">{option.hint}</div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Role model preferences */}
      {settings.hasOpenrouterApiKey && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <div className="text-xs font-medium text-zinc-300">Models per role</div>
            <span className="text-[10px] text-zinc-600">{modelsNote}</span>
            <span className="flex-1" />
            <button
              onClick={() => void loadModels(true)}
              disabled={busy !== null}
              className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-white"
              title="Fetch the model list from openrouter.ai/api/v1/models"
            >
              {busy === 'models' ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              Refresh
            </button>
          </div>
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            onKeyDown={e => e.stopPropagation()}
            placeholder="Filter models (e.g. claude, gpt-4o, gemini, free)"
            className={`${inputClass} text-xs py-1.5`}
          />
          <datalist id="openrouter-model-ids">
            {filteredModels.map(m => (
              <option key={m.id} value={m.id}>
                {m.name}
                {m.supports_tools ? ' · tools' : ''}
                {m.context_length ? ` · ${Math.round(m.context_length / 1000)}k` : ''}
              </option>
            ))}
          </datalist>
          <div className="space-y-1.5">
            <RoleRow
              label="Default"
              hint="Used by any role left blank"
              value={settings.openrouterModels.defaultModel}
              placeholder="openai/gpt-4o-mini"
              models={models}
              onChange={v => setRoleModel('defaultModel', v)}
            />
            {DIRECTOR_ROLES.map(role => (
              <RoleRow
                key={role.id}
                label={role.label}
                hint={role.hint}
                value={settings.openrouterModels[role.id]}
                placeholder={settings.openrouterModels.defaultModel || 'openai/gpt-4o-mini'}
                models={models}
                onChange={v => setRoleModel(role.id, v)}
              />
            ))}
          </div>
          <p className="text-[10px] text-zinc-600 leading-snug">
            The Director role runs tool calls; pick a model that lists “tools” support (the model list marks
            them). Others only need JSON output.
          </p>
        </div>
      )}

      <OpenAICompatibleSettings inputClass={inputClass} />
    </div>
  )
}

/**
 * Local / self-hosted OpenAI-compatible endpoint (LM Studio, vLLM, Ollama's
 * OpenAI shim, gateways). The optional key is stored by the backend exactly
 * like the other provider keys; the base URL and model id are ordinary
 * settings (not secrets).
 */
function OpenAICompatibleSettings({ inputClass }: { inputClass: string }) {
  const { settings, updateSettings, saveOpenaiCompatibleApiKey, clearApiKey } = useAppSettings()
  const [baseUrl, setBaseUrl] = useState(settings.openaiCompatibleBaseUrl)
  const [model, setModel] = useState(settings.openaiCompatibleModel)
  const [keyInput, setKeyInput] = useState('')
  const [busy, setBusy] = useState<'key' | 'models' | 'test' | 'clear' | null>(null)
  const [models, setModels] = useState<OpenRouterModelInfo[]>([])
  const [note, setNote] = useState('')

  useEffect(() => {
    setBaseUrl(settings.openaiCompatibleBaseUrl)
    setModel(settings.openaiCompatibleModel)
  }, [settings.openaiCompatibleBaseUrl, settings.openaiCompatibleModel])

  const commitEndpoint = useCallback(() => {
    const trimmedUrl = baseUrl.trim().replace(/\/+$/, '')
    const trimmedModel = model.trim()
    if (trimmedUrl !== settings.openaiCompatibleBaseUrl || trimmedModel !== settings.openaiCompatibleModel) {
      updateSettings({ openaiCompatibleBaseUrl: trimmedUrl, openaiCompatibleModel: trimmedModel })
    }
  }, [baseUrl, model, settings.openaiCompatibleBaseUrl, settings.openaiCompatibleModel, updateSettings])

  const refreshModels = useCallback(async () => {
    commitEndpoint()
    setBusy('models')
    setNote('')
    try {
      // The backend reads the base URL from settings; give the debounced sync a moment.
      await new Promise(resolve => setTimeout(resolve, 400))
      const result = await filmApi.openaiCompatibleModels()
      setModels(result.models)
      setNote(result.models.length ? `${result.models.length} models available at the endpoint` : 'The endpoint returned no models')
      if (!model.trim() && result.models[0]) {
        setModel(result.models[0].id)
        updateSettings({ openaiCompatibleModel: result.models[0].id })
      }
    } catch (e) {
      setNote(`Could not reach the endpoint: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [commitEndpoint, model, updateSettings])

  const testConnection = useCallback(async () => {
    commitEndpoint()
    setBusy('test')
    setNote('')
    try {
      await new Promise(resolve => setTimeout(resolve, 400))
      const status = await filmApi.directorStatus()
      if (!status.openai_compatible_configured) {
        setNote('Set both the base URL and a model id first')
        return
      }
      const result = await filmApi.directorChat([{ role: 'user', content: 'Reply with the single word: ready' }], {
        role: 'prompt_refinement',
      })
      setNote(`Connected · ${result.context.provider} · ${result.context.model} answered`)
    } catch (e) {
      setNote(`Connection test failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [commitEndpoint])

  const saveKey = useCallback(async () => {
    const trimmed = keyInput.trim()
    if (!trimmed) return
    setBusy('key')
    setNote('')
    try {
      await saveOpenaiCompatibleApiKey(trimmed)
      setKeyInput('')
      setNote('Endpoint key saved')
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [keyInput, saveOpenaiCompatibleApiKey])

  const clearKey = useCallback(async () => {
    setBusy('clear')
    try {
      await clearApiKey('openai-compatible')
      setNote('Endpoint key removed')
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [clearApiKey])

  const configured = settings.openaiCompatibleBaseUrl.trim() !== '' && settings.openaiCompatibleModel.trim() !== ''

  return (
    <div className="space-y-2 pt-3 border-t border-zinc-800/70">
      <div className="flex items-center gap-2">
        <div className="text-xs font-medium text-zinc-300">Local / OpenAI-compatible endpoint</div>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${configured ? 'bg-emerald-500/10 text-emerald-300' : 'bg-zinc-800 text-zinc-500'}`}>
          {configured ? 'configured' : 'not configured'}
        </span>
      </div>
      <p className="text-[10px] text-zinc-600 leading-snug">
        Run the AI Director fully offline with LM Studio, vLLM or Ollama (OpenAI-compatible API). Enter the{' '}
        <code className="text-zinc-400">/v1</code> base URL, refresh the model list, pick a model. A key is only
        needed if your server requires one; it is stored by the local backend like the other keys.
      </p>
      <div className="grid grid-cols-[1fr_1fr] gap-2">
        <input
          value={baseUrl}
          onChange={e => setBaseUrl(e.target.value)}
          onBlur={commitEndpoint}
          onKeyDown={e => {
            e.stopPropagation()
            if (e.key === 'Enter') commitEndpoint()
          }}
          placeholder="http://127.0.0.1:1234/v1"
          aria-label="OpenAI-compatible base URL"
          className={`${inputClass} text-xs py-1.5 font-mono`}
        />
        <div className="flex items-center gap-1.5">
          <input
            list="openai-compatible-model-ids"
            value={model}
            onChange={e => setModel(e.target.value)}
            onBlur={commitEndpoint}
            onKeyDown={e => {
              e.stopPropagation()
              if (e.key === 'Enter') commitEndpoint()
            }}
            placeholder="model id (e.g. qwen2.5-7b-instruct)"
            aria-label="OpenAI-compatible model id"
            className={`${inputClass} text-xs py-1.5 font-mono`}
          />
          <datalist id="openai-compatible-model-ids">
            {models.map(m => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </datalist>
          <button
            onClick={() => void refreshModels()}
            disabled={busy !== null || !baseUrl.trim()}
            className="flex items-center gap-1 text-[11px] text-zinc-300 hover:text-white px-2 py-1.5 rounded bg-zinc-800 border border-zinc-700 disabled:opacity-40 whitespace-nowrap"
            title="GET <base URL>/models"
          >
            {busy === 'models' ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            Models
          </button>
        </div>
      </div>
      <div className="flex gap-2">
        <input
          type="password"
          autoComplete="off"
          value={keyInput}
          onChange={e => setKeyInput(e.target.value)}
          onKeyDown={e => {
            e.stopPropagation()
            if (e.key === 'Enter') void saveKey()
          }}
          placeholder={settings.hasOpenaiCompatibleApiKey ? 'Key stored — enter a new one to replace' : 'API key (optional)'}
          aria-label="OpenAI-compatible endpoint API key"
          className={`${inputClass} text-xs py-1.5`}
        />
        <button
          onClick={() => void saveKey()}
          disabled={!keyInput.trim() || busy !== null}
          className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 whitespace-nowrap"
        >
          {busy === 'key' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Save key'}
        </button>
        {settings.hasOpenaiCompatibleApiKey && (
          <button
            onClick={() => void clearKey()}
            disabled={busy !== null}
            className="flex items-center gap-1 text-xs text-zinc-400 hover:text-red-300 px-2 py-1.5 rounded bg-zinc-800 border border-zinc-700"
          >
            <Trash2 className="h-3 w-3" /> Remove
          </button>
        )}
        <button
          onClick={() => void testConnection()}
          disabled={busy !== null || !baseUrl.trim() || !model.trim()}
          className="flex items-center gap-1 text-xs text-zinc-300 hover:text-white px-2 py-1.5 rounded bg-zinc-800 border border-zinc-700 disabled:opacity-40 whitespace-nowrap"
          title="Sends one tiny chat request to the endpoint"
        >
          {busy === 'test' ? <Loader2 className="h-3 w-3 animate-spin" /> : <ShieldCheck className="h-3 w-3" />}
          Test connection
        </button>
      </div>
      {note && <div className="text-[11px] text-zinc-400">{note}</div>}
    </div>
  )
}

function RoleRow({
  label,
  hint,
  value,
  placeholder,
  models,
  onChange,
}: {
  label: string
  hint: string
  value: string
  placeholder: string
  models: OpenRouterModelInfo[]
  onChange: (value: string) => void
}) {
  const info = models.find(m => m.id === (value || placeholder))
  return (
    <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
      <div>
        <div className="text-xs text-zinc-200">{label}</div>
        <div className="text-[9px] text-zinc-600 leading-tight">{hint}</div>
      </div>
      <div className="flex items-center gap-1.5">
        <input
          list="openrouter-model-ids"
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => e.stopPropagation()}
          placeholder={placeholder}
          aria-label={`${label} model`}
          className="flex-1 px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-xs text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
        />
        {info && (
          <span
            className={`text-[9px] px-1 py-0.5 rounded ${info.supports_tools ? 'bg-emerald-900/50 text-emerald-300' : 'bg-zinc-800 text-zinc-500'}`}
            title={info.supports_tools ? 'Supports tool calling' : 'No tool calling — JSON plan fallback is used'}
          >
            {info.supports_tools ? 'tools' : 'no tools'}
          </span>
        )}
      </div>
    </div>
  )
}
