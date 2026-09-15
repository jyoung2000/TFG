import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Check, ChevronDown, ChevronRight, Copy, Loader2, Wand2 } from 'lucide-react'
import { promptsApi, type CompileSource } from '../lib/prompts-api'
import {
  BASIS_LABELS,
  BRIEF_SECTIONS,
  EMPTY_BRIEF,
  STYLE_LABELS,
  briefValue,
  type CompiledPrompt,
  type ShotBrief,
} from '../types/prompts'

/**
 * One shot, compiled for each model that might render it.
 *
 * The brief is shown above the prompts on purpose: the compiled strings are
 * disposable, the brief is what was actually said about the shot. Anything a
 * target could not carry is listed under its prompt rather than quietly lost,
 * and a model this app has no convention for is labelled as such rather than
 * presented as tailored.
 */
export function CompiledPrompts({
  source,
  models,
  title = 'Compiled for each model',
}: {
  source: CompileSource
  /** The models to compile for, in the order they should appear. */
  models: string[]
  title?: string
}) {
  const [brief, setBrief] = useState<ShotBrief>(EMPTY_BRIEF)
  const [prompts, setPrompts] = useState<CompiledPrompt[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [showBrief, setShowBrief] = useState(false)
  const [copied, setCopied] = useState('')

  const key = JSON.stringify([source, models])
  const load = useCallback(async () => {
    if (models.length === 0) return
    setLoading(true)
    setError('')
    try {
      const result = await promptsApi.compile(models, source)
      setBrief(result.brief)
      setPrompts(result.prompts)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not compile the prompt.')
    } finally {
      setLoading(false)
    }
    // `key` stands in for the source and model list, which are fresh objects
    // on every render and would otherwise refetch forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  useEffect(() => {
    void load()
  }, [load])

  const copy = async (model: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(model)
      window.setTimeout(() => setCopied(''), 1500)
    } catch {
      // Clipboard access can be denied; the text is on screen and selectable.
      setError('Could not reach the clipboard — select the text instead.')
    }
  }

  const filled = BRIEF_SECTIONS.filter(section => briefValue(brief, section.key))

  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-zinc-500">
        <Wand2 className="h-3 w-3" /> {title}
        {loading && <Loader2 className="h-3 w-3 animate-spin" />}
      </h3>

      {error && (
        <p className="flex items-start gap-1.5 rounded border border-red-900/60 bg-red-950/40 px-2 py-1 text-[11px] text-red-300">
          <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
          {error}
        </p>
      )}

      {/* The brief first: it is what was said about the shot, and every prompt
          below is only a rendering of it. */}
      <div className="rounded border border-zinc-800 bg-zinc-900/40">
        <button
          type="button"
          onClick={() => setShowBrief(!showBrief)}
          aria-expanded={showBrief}
          className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[11px] text-zinc-300 hover:bg-zinc-800/40"
        >
          {showBrief ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          The shot, before any model sees it
          <span className="ml-auto text-zinc-600">{filled.length} of {BRIEF_SECTIONS.length} sections</span>
        </button>
        {showBrief && (
          <dl className="space-y-1 border-t border-zinc-800 px-2 py-2 text-[11px]">
            {filled.length === 0 ? (
              <p className="text-zinc-600">Nothing described yet.</p>
            ) : (
              filled.map(section => (
                <div key={section.key} className="flex gap-2">
                  <dt className="w-28 flex-shrink-0 text-zinc-600">{section.label}</dt>
                  <dd className="flex-1 text-zinc-300">{briefValue(brief, section.key)}</dd>
                </div>
              ))
            )}
          </dl>
        )}
      </div>

      {models.length === 0 ? (
        <p className="text-[11px] text-zinc-600">Choose a model to see how this shot would be written for it.</p>
      ) : (
        prompts.map(compiled => (
          <article key={compiled.model} className="rounded border border-zinc-800 bg-zinc-900/40 p-2 space-y-1.5">
            <header className="flex items-center gap-2">
              <span className="flex-1 truncate text-[11px] text-white">{compiled.model}</span>
              <span className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-400">
                {STYLE_LABELS[compiled.style]}
              </span>
              <button
                type="button"
                onClick={() => void copy(compiled.model, compiled.prompt)}
                aria-label={`Copy the prompt for ${compiled.model}`}
                className="rounded border border-zinc-700 p-1 text-zinc-400 hover:bg-zinc-800"
              >
                {copied === compiled.model ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
              </button>
            </header>

            <p className="whitespace-pre-wrap rounded bg-zinc-950/60 px-2 py-1.5 text-[11px] leading-relaxed text-zinc-200 select-text">
              {compiled.prompt || <span className="text-zinc-600">Nothing to say about this shot yet.</span>}
            </p>
            {compiled.negative_prompt && (
              <p className="text-[10px] text-zinc-500 select-text">
                <span className="text-zinc-600">Negative: </span>
                {compiled.negative_prompt}
              </p>
            )}

            {/* Where the convention came from, and whether it applies here. */}
            <p className="text-[10px] leading-relaxed text-zinc-500">
              <span className={compiled.matched ? 'text-zinc-400' : 'text-amber-300'}>
                {compiled.matched ? compiled.target_label : 'Not a model this app has a convention for'}
              </span>
              {' · '}
              {BASIS_LABELS[compiled.basis]}. {compiled.note}
            </p>

            {compiled.dropped.length > 0 && (
              <ul className="space-y-0.5 border-t border-zinc-800 pt-1.5 text-[10px] text-amber-300/80">
                {compiled.dropped.map(reason => (
                  <li key={reason}>Left out: {reason}</li>
                ))}
              </ul>
            )}
          </article>
        ))
      )}
    </section>
  )
}
