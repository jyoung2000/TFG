import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Info, Loader2, Megaphone, Send, Trash2 } from 'lucide-react'
import { useAppSettings } from '../../contexts/AppSettingsContext'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi } from '../../lib/film-api'
import type { DirectorChatMessage, DirectorContextDetails, DirectorStatus } from '../../types/film'

interface Turn extends DirectorChatMessage {
  steps?: { name: string; ok: boolean; error: string }[]
  context?: DirectorContextDetails | null
  error?: boolean
}

/**
 * AI Director chat: a natural-language instruction is executed by the backend
 * as tool calls against the same film store the UI reads — results land in the
 * storyboard immediately after the refresh. Every reply can disclose exactly
 * what context was sent to which model ("context details").
 */
export function DirectorBar({
  selectedSceneId,
  selectedShotId,
}: {
  selectedSceneId: string | null
  selectedShotId: string | null
}) {
  const { film, refresh } = useFilm()
  const { settings, hasDirectorProvider } = useAppSettings()
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const [expanded, setExpanded] = useState(false)
  const [status, setStatus] = useState<DirectorStatus | null>(null)
  const [showContextFor, setShowContextFor] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    void filmApi
      .directorStatus()
      .then(next => {
        if (!cancelled) setStatus(next)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [settings.hasOpenrouterApiKey, settings.hasGeminiApiKey, settings.directorProvider, settings.openrouterModels])

  const run = useCallback(async () => {
    if (!film || !instruction.trim() || busy) return
    const text = instruction.trim()
    setBusy(true)
    setInstruction('')
    setExpanded(true)
    const history: DirectorChatMessage[] = turns
      .filter(t => !t.error)
      .map(t => ({ role: t.role, content: t.content }))
    setTurns(prev => [...prev, { role: 'user', content: text }])
    try {
      const result = await filmApi.directorInstruct(
        film.id,
        text,
        selectedSceneId ?? undefined,
        selectedShotId ?? undefined,
        history,
      )
      const failed = result.results.filter(r => !r.ok)
      const summary =
        result.reply ||
        result.plan_summary ||
        (failed.length === 0 ? `Done (${result.results.length} steps)` : `Stopped at "${failed[0].name}": ${failed[0].error}`)
      setTurns(prev => [
        ...prev,
        {
          role: 'assistant',
          content: summary,
          steps: result.results.map(r => ({ name: r.name, ok: r.ok, error: r.error })),
          context: result.context,
        },
      ])
      await refresh()
    } catch (e) {
      setTurns(prev => [
        ...prev,
        { role: 'assistant', content: e instanceof Error ? e.message : String(e), error: true },
      ])
    } finally {
      setBusy(false)
    }
  }, [film, instruction, busy, turns, selectedSceneId, selectedShotId, refresh])

  const enabled = hasDirectorProvider
  const directorRole = status?.roles.find(r => r.role === 'director')
  const providerLabel = directorRole && directorRole.provider !== 'none' ? `${directorRole.provider} · ${directorRole.model}` : ''
  const lastTurn = turns[turns.length - 1]

  return (
    <div className="border-t border-zinc-800 bg-zinc-900/80">
      {/* Transcript */}
      {expanded && turns.length > 0 && (
        <div className="max-w-4xl mx-auto px-3 pt-2 max-h-56 overflow-y-auto space-y-1.5" role="log" aria-live="polite">
          {turns.map((turn, index) => (
            <div key={index} className={`text-[11px] ${turn.role === 'user' ? 'text-zinc-300' : turn.error ? 'text-red-300' : 'text-violet-200'}`}>
              <span className="text-zinc-600 mr-1">{turn.role === 'user' ? 'You' : 'Director'}</span>
              {turn.content}
              {turn.steps && turn.steps.length > 0 && (
                <span className="ml-1 text-zinc-500">
                  ·{' '}
                  {turn.steps.map((s, i) => (
                    <span key={i} className={s.ok ? 'text-zinc-500' : 'text-amber-400'} title={s.error || s.name}>
                      {s.name}
                      {i < turn.steps!.length - 1 ? ', ' : ''}
                    </span>
                  ))}
                </span>
              )}
              {turn.context && (
                <button
                  onClick={() => setShowContextFor(showContextFor === index ? null : index)}
                  className="ml-2 inline-flex items-center gap-0.5 text-[10px] text-zinc-500 hover:text-zinc-300 underline underline-offset-2"
                  aria-expanded={showContextFor === index}
                >
                  <Info className="h-2.5 w-2.5" /> context details
                </button>
              )}
              {turn.context && showContextFor === index && <ContextDetails context={turn.context} />}
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 max-w-4xl mx-auto px-3 py-2">
        <Megaphone className="h-4 w-4 text-violet-400 shrink-0" />
        <input
          value={instruction}
          onChange={e => setInstruction(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') void run()
          }}
          aria-label="AI Director instruction"
          placeholder={
            enabled
              ? 'Direct the film: "Create a six second medium OTS shot — Sarah foreground left, looking toward John, slow push-in"'
              : 'AI Director needs an OpenRouter or Gemini API key (Settings → API Keys)'
          }
          disabled={!enabled || busy}
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600 disabled:opacity-50"
        />
        <button
          onClick={() => void run()}
          disabled={!enabled || busy || !instruction.trim()}
          aria-label="Send instruction"
          className="p-1.5 rounded-lg bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
        </button>
        {turns.length > 0 && (
          <>
            <button
              onClick={() => setExpanded(v => !v)}
              className="p-1 rounded text-zinc-500 hover:text-zinc-300"
              aria-label={expanded ? 'Collapse director transcript' : 'Expand director transcript'}
            >
              {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
            </button>
            <button
              onClick={() => {
                setTurns([])
                setShowContextFor(null)
              }}
              className="p-1 rounded text-zinc-600 hover:text-red-400"
              aria-label="Clear director conversation"
              title="Clear conversation (the film itself is unchanged)"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>
      <div className="max-w-4xl mx-auto px-3 pb-1.5 flex items-center gap-2 text-[10px] text-zinc-600">
        {providerLabel && <span className="font-mono">{providerLabel}</span>}
        {!expanded && lastTurn && lastTurn.role === 'assistant' && (
          <span className={`truncate ${lastTurn.error ? 'text-red-400' : 'text-zinc-400'}`}>{lastTurn.content}</span>
        )}
        {status?.message && !enabled && <span className="text-amber-500/80 truncate">{status.message}</span>}
      </div>
    </div>
  )
}

function ContextDetails({ context }: { context: DirectorContextDetails }) {
  return (
    <div className="mt-1 mb-1 rounded border border-zinc-800 bg-zinc-950/60 p-2 text-[10px] text-zinc-400 grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono">
      <span>provider</span>
      <span className="text-zinc-200">{context.provider}</span>
      <span>model</span>
      <span className="text-zinc-200">{context.model}</span>
      <span>role</span>
      <span className="text-zinc-200">{context.role}</span>
      <span>model turns / tool calls</span>
      <span className="text-zinc-200">
        {context.steps} / {context.tool_calls}
      </span>
      <span>chars sent (total)</span>
      <span className="text-zinc-200">{context.prompt_chars.toLocaleString()}</span>
      <span>project summary chars</span>
      <span className="text-zinc-200">{context.project_summary_chars.toLocaleString()}</span>
      <span>tokens in / out</span>
      <span className="text-zinc-200">
        {context.prompt_tokens ?? '—'} / {context.completion_tokens ?? '—'}
      </span>
      <span className="col-span-2 text-zinc-500 font-sans">Sent: {context.scope}</span>
    </div>
  )
}
