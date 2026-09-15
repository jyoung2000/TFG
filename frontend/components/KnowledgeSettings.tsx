import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  Loader2,
  RotateCcw,
  Upload,
} from 'lucide-react'
import { Button } from './ui/button'
import { knowledgeApi } from '../lib/knowledge-api'
import { logger } from '../lib/logger'
import {
  approvalRate,
  successRate,
  OBSERVATION_KIND_LABELS,
  type KnowledgeExport,
  type KnowledgeSummary,
  type LearningSettings,
  type ModelProfile,
  type Observation,
  type ObservationKind,
  type PromptPattern,
} from '../types/knowledge'

/**
 * Settings → Knowledge: what this app has learned about the models it runs,
 * and the controls to stop it, forget it, or move it to another machine.
 *
 * The screen's job is to make the difference between a count and a guess
 * visible. Every statement is shown with the kind of claim it is and the
 * sample behind it, so "failed 4 of 5 renders" and "overanimates static
 * shots" never read alike.
 */
export function KnowledgeSettings() {
  const [summary, setSummary] = useState<KnowledgeSummary | null>(null)
  const [profiles, setProfiles] = useState<ModelProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [expanded, setExpanded] = useState<string>('')
  const [busy, setBusy] = useState('')
  const importInputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [nextSummary, nextProfiles] = await Promise.all([
        knowledgeApi.summary(),
        knowledgeApi.profiles(),
      ])
      setSummary(nextSummary)
      setProfiles(nextProfiles)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read what this app has learned.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const learning = summary?.learning

  const setLearning = async (patch: Partial<LearningSettings>) => {
    if (!learning) return
    const next = { ...learning, ...patch }
    setSummary({ ...summary!, learning: next })
    try {
      await knowledgeApi.updateLearning(next)
      setNotice(next.enabled ? 'Saved.' : 'Learning off — nothing new will be recorded.')
    } catch (err) {
      logger.error(`Failed to update learning settings: ${err}`)
      setError(err instanceof Error ? err.message : 'Could not save that.')
      void load()
    }
  }

  const doExport = async () => {
    setBusy('export')
    setError('')
    try {
      const payload = await knowledgeApi.export()
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `tfg-knowledge-${new Date().toISOString().slice(0, 10)}.json`
      anchor.click()
      URL.revokeObjectURL(url)
      setNotice(`Exported ${payload.events.length} events.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed.')
    } finally {
      setBusy('')
    }
  }

  const doImport = async (file: File) => {
    setBusy('import')
    setError('')
    try {
      // Parsed here rather than posted raw: a file the user picked is input,
      // and the backend rejects any schema version it does not understand.
      const parsed = JSON.parse(await file.text()) as KnowledgeExport
      const result = await knowledgeApi.import(parsed, false)
      setNotice(`Merged: ${result.status}.`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That file is not a knowledge export.')
    } finally {
      setBusy('')
      if (importInputRef.current) importInputRef.current.value = ''
    }
  }

  const doReset = async (model = '') => {
    const what = model ? `everything learned about ${model}` : 'everything this app has learned'
    if (!window.confirm(`Forget ${what}? This cannot be undone.`)) return
    setBusy(model || 'reset')
    setError('')
    try {
      const result = await knowledgeApi.reset(model ? { model } : {})
      setNotice(result.status)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not clear that.')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-violet-400" />
          <h3 className="text-sm font-semibold text-white">What this app has learned</h3>
        </div>
        <p className="mt-1 text-xs text-zinc-500 leading-relaxed">
          Built only from your own renders on this machine. Nothing is sent anywhere. Counts are
          arithmetic over what happened; anything that generalises from them is labelled as the kind
          of claim it is, with the sample behind it.
        </p>
      </header>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-300">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {notice && !error && (
        <div className="flex items-start gap-2 rounded-lg border border-zinc-700 bg-zinc-800/60 px-3 py-2 text-xs text-zinc-300">
          <Check className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-400" />
          <span>{notice}</span>
        </div>
      )}

      {/* ---- what is being remembered ---------------------------------- */}
      {learning && (
        <section className="space-y-3">
          <Toggle
            label="Learn from what I do"
            blurb="Off stops collection entirely — not just the display. Existing knowledge is kept until you clear it."
            checked={learning.enabled}
            onChange={enabled => void setLearning({ enabled })}
          />
          <div className={`grid gap-2 sm:grid-cols-2 ${learning.enabled ? '' : 'pointer-events-none opacity-40'}`}>
            <Toggle
              small
              label="Renders"
              blurb="Which model ran, how long it took, whether it finished."
              checked={learning.generation}
              onChange={generation => void setLearning({ generation })}
            />
            <Toggle
              small
              label="Approvals"
              blurb="Which takes you kept and which you rejected."
              checked={learning.approval}
              onChange={approval => void setLearning({ approval })}
            />
            <Toggle
              small
              label="Edits"
              blurb="Prompt rewrites, model switches, continuity corrections."
              checked={learning.editing}
              onChange={editing => void setLearning({ editing })}
            />
            <Toggle
              small
              label="Ratings and notes"
              blurb="Anything you explicitly tell it about a result."
              checked={learning.feedback}
              onChange={feedback => void setLearning({ feedback })}
            />
          </div>
        </section>
      )}

      {/* ---- the store itself ------------------------------------------- */}
      {summary && (
        <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-400">
            <span><span className="text-white">{summary.event_count}</span> events recorded</span>
            <span><span className="text-white">{summary.model_count}</span> models used</span>
            <span><span className="text-white">{summary.observation_count}</span> observations derived</span>
          </div>
          <p className="mt-2 break-all font-mono text-[11px] text-zinc-600 select-text">{summary.database}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="outline" className="h-8 border-zinc-700 text-xs" onClick={() => void doExport()} disabled={busy === 'export'}>
              {busy === 'export' ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <Download className="mr-1.5 h-3 w-3" />}
              Export
            </Button>
            <Button
              variant="outline"
              className="h-8 border-zinc-700 text-xs"
              onClick={() => importInputRef.current?.click()}
              disabled={busy === 'import'}
            >
              {busy === 'import' ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <Upload className="mr-1.5 h-3 w-3" />}
              Import
            </Button>
            <input
              ref={importInputRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={event => {
                const file = event.target.files?.[0]
                if (file) void doImport(file)
              }}
            />
            <Button
              variant="outline"
              className="h-8 border-red-900/60 text-xs text-red-300 hover:bg-red-950/40"
              onClick={() => void doReset()}
              disabled={busy === 'reset' || summary.event_count === 0}
            >
              {busy === 'reset' ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <RotateCcw className="mr-1.5 h-3 w-3" />}
              Forget everything
            </Button>
          </div>
        </section>
      )}

      {/* ---- per-model ---------------------------------------------------- */}
      {loading ? (
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading…
        </div>
      ) : profiles.length === 0 ? (
        <p className="rounded-lg border border-dashed border-zinc-800 px-3 py-6 text-center text-xs text-zinc-500">
          Nothing learned yet. Render a few shots and this fills in with what actually happened.
        </p>
      ) : (
        <div className="space-y-2">
          {profiles.map(profile => (
            <ProfileCard
              key={profile.model}
              profile={profile}
              open={expanded === profile.model}
              onToggle={() => setExpanded(expanded === profile.model ? '' : profile.model)}
              onForget={() => void doReset(profile.model)}
              busy={busy === profile.model}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ProfileCard({
  profile,
  open,
  onToggle,
  onForget,
  busy,
}: {
  profile: ModelProfile
  open: boolean
  onToggle: () => void
  onForget: () => void
  busy: boolean
}) {
  const success = successRate(profile)
  const approval = approvalRate(profile)
  const worked = profile.prompt_patterns.filter(p => p.verdict === 'worked')
  const struggled = profile.prompt_patterns.filter(p => p.verdict === 'struggled')

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-zinc-800/40"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 text-zinc-500" /> : <ChevronRight className="h-3.5 w-3.5 text-zinc-500" />}
        <span className="flex-1 truncate text-sm text-white">{profile.label || profile.model}</span>
        {profile.provider && <span className="text-[11px] text-zinc-500">{profile.provider}</span>}
        <span className="text-[11px] text-zinc-400">{profile.runs} events</span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-zinc-800 px-3 py-3">
          {/* usage statistics */}
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] text-zinc-400 sm:grid-cols-4">
            <Stat label="Completed" value={`${profile.successes}`} />
            <Stat label="Failed" value={`${profile.failures}`} />
            <Stat label="Cancelled" value={`${profile.cancellations}`} />
            <Stat label="Success rate" value={success === null ? 'no data' : `${Math.round(success * 100)}%`} />
            <Stat label="Approved" value={`${profile.approvals}`} />
            <Stat label="Rejected" value={`${profile.rejections}`} />
            <Stat label="Kept" value={approval === null ? 'no data' : `${Math.round(approval * 100)}%`} />
            <Stat
              label="Average time"
              value={profile.average_seconds === null ? 'no data' : `${profile.average_seconds.toFixed(1)}s`}
            />
          </div>

          {/* what those numbers suggest */}
          <div>
            <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Observations</h4>
            {profile.observations.length === 0 ? (
              <p className="text-xs text-zinc-600">Not enough history to say anything yet.</p>
            ) : (
              <ul className="space-y-1.5">
                {profile.observations.map(observation => (
                  <ObservationRow key={observation.id} observation={observation} />
                ))}
              </ul>
            )}
          </div>

          {/* prompt vocabulary */}
          {(worked.length > 0 || struggled.length > 0) && (
            <div className="grid gap-3 sm:grid-cols-2">
              <PatternList title="Prompt terms that worked" tone="good" patterns={worked} />
              <PatternList title="Prompt terms that struggled" tone="bad" patterns={struggled} />
            </div>
          )}

          <Button
            variant="outline"
            className="h-7 border-red-900/60 text-[11px] text-red-300 hover:bg-red-950/40"
            onClick={onForget}
            disabled={busy}
          >
            {busy ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <RotateCcw className="mr-1.5 h-3 w-3" />}
            Forget this model
          </Button>
        </div>
      )}
    </div>
  )
}

const KIND_TONE: Record<ObservationKind, string> = {
  fact: 'border-zinc-600 text-zinc-300',
  observed_pattern: 'border-sky-800 text-sky-300',
  user_preference: 'border-violet-800 text-violet-300',
  model_recommendation: 'border-emerald-800 text-emerald-300',
  hypothesis: 'border-amber-800 text-amber-300',
}

function ObservationRow({ observation }: { observation: Observation }) {
  return (
    <li className="flex items-start gap-2 text-xs">
      <span
        className={`mt-0.5 flex-shrink-0 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${KIND_TONE[observation.kind]}`}
      >
        {OBSERVATION_KIND_LABELS[observation.kind]}
      </span>
      <span className="flex-1 text-zinc-300">
        {observation.statement}
        <span className="ml-1.5 text-[11px] text-zinc-600">
          {/* Confidence is meaningless without the sample it came from. */}
          {Math.round(observation.confidence * 100)}% confidence, {observation.sample_size}{' '}
          {observation.sample_size === 1 ? 'observation' : 'observations'}
        </span>
      </span>
    </li>
  )
}

function PatternList({
  title,
  tone,
  patterns,
}: {
  title: string
  tone: 'good' | 'bad'
  patterns: PromptPattern[]
}) {
  return (
    <div>
      <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">{title}</h4>
      {patterns.length === 0 ? (
        <p className="text-xs text-zinc-600">Nothing yet.</p>
      ) : (
        <ul className="space-y-1">
          {patterns.map(pattern => (
            <li key={pattern.phrase} className="text-xs">
              <span className={tone === 'good' ? 'text-emerald-300' : 'text-amber-300'}>{pattern.phrase}</span>
              <span className="ml-1.5 text-[11px] text-zinc-600">
                used {pattern.uses}×, {pattern.successes + pattern.approvals} kept,{' '}
                {pattern.failures + pattern.rejections} not
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-zinc-600">{label}</span>{' '}
      <span className="text-zinc-200">{value}</span>
    </div>
  )
}

function Toggle({
  label,
  blurb,
  checked,
  onChange,
  small,
}: {
  label: string
  blurb: string
  checked: boolean
  onChange: (next: boolean) => void
  small?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`flex w-full items-start justify-between gap-3 rounded-lg border-2 bg-zinc-800/50 text-left transition-colors ${
        small ? 'p-3' : 'p-4'
      } ${checked ? 'border-violet-500/70' : 'border-transparent hover:border-zinc-600'}`}
    >
      <span className="flex-1">
        <span className={`block font-medium text-white ${small ? 'text-xs' : 'text-sm'}`}>{label}</span>
        <span className="mt-1 block text-[11px] leading-relaxed text-zinc-400">{blurb}</span>
      </span>
      <span
        className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border-2 ${
          checked ? 'border-violet-500 bg-violet-500' : 'border-zinc-600'
        }`}
      >
        {checked && <Check className="h-3 w-3 text-white" />}
      </span>
    </button>
  )
}
