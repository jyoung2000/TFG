import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeftRight,
  ChevronDown,
  ChevronRight,
  Clapperboard,
  Copy,
  Film,
  Loader2,
  Scissors,
  Sparkles,
  Trash2,
  Undo2,
  Wand2,
} from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { timelineApi } from '../../lib/timeline-api'
import {
  TRANSITION_LABELS,
  formatSeconds,
  type DirectorAction,
  type TimelineActionName,
  type TimelineEntry,
  type TimelineView,
  type TransitionKind,
} from '../../types/timeline'

/**
 * The film's running order, and the edits that shape it.
 *
 * This is the same timeline the AI Director edits — every button here goes
 * through the same endpoint its tool calls do, which is why undo covers both
 * and why the history below shows a model's edits beside a person's. There is
 * no separate "AI timeline"; there is one edit, and two things that can change
 * it.
 */
export function TimelinePanel() {
  const { film, refresh } = useFilm()
  const projectId = film?.id ?? ''

  const [timeline, setTimeline] = useState<TimelineView | null>(null)
  const [history, setHistory] = useState<DirectorAction[]>([])
  const [undoable, setUndoable] = useState(0)
  const [selected, setSelected] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [showHistory, setShowHistory] = useState(false)

  const load = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const [view, log] = await Promise.all([
        timelineApi.view(projectId),
        timelineApi.history(projectId),
      ])
      setTimeline(view)
      setHistory(log.actions)
      setUndoable(log.undoable)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read the timeline.')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  const run = async (action: TimelineActionName, params: Record<string, unknown>, label: string) => {
    if (!projectId) return
    setBusy(label)
    setError('')
    try {
      const result = await timelineApi.apply(projectId, action, params)
      setTimeline(result.timeline)
      setNote(result.action.summary)
      await Promise.all([refresh(), load()])
    } catch (err) {
      // A refused edit changed nothing, so there is nothing to undo — just say why.
      setError(err instanceof Error ? err.message : 'That edit was refused.')
    } finally {
      setBusy('')
    }
  }

  const undo = async () => {
    if (!projectId) return
    setBusy('undo')
    setError('')
    try {
      const result = await timelineApi.undo(projectId)
      setTimeline(result.timeline)
      setNote(`Undid: ${result.action.summary}`)
      await Promise.all([refresh(), load()])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nothing to undo.')
    } finally {
      setBusy('')
    }
  }

  const entry = timeline?.entries.find(e => e.shot_id === selected) ?? null

  if (!film) return null

  return (
    <div className="mx-auto max-w-4xl space-y-3">
      <header className="flex flex-wrap items-center gap-2">
        <Film className="h-4 w-4 text-violet-400" />
        <h3 className="text-sm font-semibold text-white">Timeline</h3>
        {timeline && (
          <span className="text-[11px] text-zinc-500">
            {timeline.shot_count} shots · {formatSeconds(timeline.total_seconds)} ·{' '}
            {timeline.rendered_count} rendered
          </span>
        )}
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => void undo()}
          disabled={busy !== '' || undoable === 0}
          title={undoable === 0 ? 'Nothing to undo' : 'Put the film back the way it was before the last edit'}
          className="flex items-center gap-1 rounded border border-zinc-700 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
        >
          {busy === 'undo' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Undo2 className="h-3 w-3" />}
          Undo{undoable > 0 ? ` (${undoable})` : ''}
        </button>
      </header>

      {error && (
        <p className="flex items-start gap-1.5 rounded border border-red-900/60 bg-red-950/40 px-2 py-1.5 text-[11px] text-red-300">
          <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
          {error}
        </p>
      )}
      {note && !error && <p className="text-[11px] text-zinc-500">{note}</p>}

      {/* ---- the running order ---- */}
      {loading && !timeline ? (
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading…
        </div>
      ) : !timeline || timeline.entries.length === 0 ? (
        <p className="rounded-lg border border-dashed border-zinc-800 px-3 py-6 text-center text-xs text-zinc-500">
          No shots yet. Add a scene and a shot, and the running order appears here.
        </p>
      ) : (
        <ol className="space-y-1">
          {timeline.entries.map((item, index) => (
            <TimelineRow
              key={item.shot_id}
              entry={item}
              first={index === 0}
              selected={selected === item.shot_id}
              onSelect={() => setSelected(selected === item.shot_id ? '' : item.shot_id)}
            />
          ))}
        </ol>
      )}

      {/* ---- what to do with the selected shot ---- */}
      {entry && (
        <ShotEdits
          entry={entry}
          busy={busy}
          scenes={(timeline?.entries ?? []).map(e => ({ id: e.scene_id, title: e.scene_title }))}
          onRun={run}
        />
      )}

      {/* ---- edits that shape the whole film ---- */}
      <div className="flex flex-wrap gap-1.5 border-t border-zinc-800 pt-2">
        <Action
          icon={<Sparkles className="h-3 w-3" />}
          label="Opening"
          title="Add a shot at the very front that fades in"
          busy={busy === 'opening'}
          onClick={() => void run('add_opening', { title: 'Opening' }, 'opening')}
        />
        <Action
          icon={<Sparkles className="h-3 w-3" />}
          label="Ending"
          title="Add a shot at the very end that fades out"
          busy={busy === 'ending'}
          onClick={() => void run('add_ending', { title: 'Ending' }, 'ending')}
        />
        <Action
          icon={<Clapperboard className="h-3 w-3" />}
          label="Montage"
          title="Cut this scene's shots into a montage — short, evenly timed, no gaps. Only the rhythm changes."
          busy={busy === 'montage'}
          disabled={!entry}
          onClick={() => {
            if (!entry || !timeline) return
            const ids = timeline.entries.filter(e => e.scene_id === entry.scene_id).map(e => e.shot_id)
            void run('build_montage', { scene_id: entry.scene_id, shot_ids: ids, shot_seconds: 1.2 }, 'montage')
          }}
        />
        <Action
          icon={<ArrowLeftRight className="h-3 w-3" />}
          label="Align scene"
          title="Give every shot in the selected scene the same length"
          busy={busy === 'align'}
          disabled={!entry}
          onClick={() => {
            if (!entry) return
            void run('align_durations', { scene_id: entry.scene_id, duration_seconds: 4 }, 'align')
          }}
        />
        <Action
          icon={<Wand2 className="h-3 w-3" />}
          label="Normalise"
          title="Tidy gaps and ordering across the whole film. Conservative — it does not reshape how long shots run."
          busy={busy === 'normalize'}
          onClick={() => void run('normalize_timeline', { gap_seconds: 0.25 }, 'normalize')}
        />
      </div>

      {/* ---- the record ---- */}
      <div className="rounded border border-zinc-800 bg-zinc-900/40">
        <button
          type="button"
          onClick={() => setShowHistory(!showHistory)}
          aria-expanded={showHistory}
          className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[11px] text-zinc-300 hover:bg-zinc-800/40"
        >
          {showHistory ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          Edit history
          <span className="ml-auto text-zinc-600">{history.length} edits</span>
        </button>
        {showHistory && (
          <ol className="max-h-64 space-y-1 overflow-y-auto border-t border-zinc-800 px-2 py-2">
            {history.length === 0 ? (
              <p className="text-[11px] text-zinc-600">No edits yet.</p>
            ) : (
              [...history].reverse().map(action => (
                <li key={action.id} className="flex items-start gap-2 text-[11px]">
                  {/* Who made the edit is worth seeing at a glance when some of
                      them were made by a model. */}
                  <span
                    className={`mt-0.5 flex-shrink-0 rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${
                      action.actor === 'director'
                        ? 'border-violet-800 text-violet-300'
                        : 'border-zinc-700 text-zinc-400'
                    }`}
                  >
                    {action.actor === 'director' ? 'AI' : 'You'}
                  </span>
                  <span className={`flex-1 ${action.undone ? 'text-zinc-600 line-through' : 'text-zinc-300'}`}>
                    {action.summary}
                  </span>
                  <span className="text-[10px] text-zinc-600">
                    {new Date(action.created_at).toLocaleTimeString()}
                  </span>
                </li>
              ))
            )}
          </ol>
        )}
      </div>
    </div>
  )
}

function TimelineRow({
  entry,
  first,
  selected,
  onSelect,
}: {
  entry: TimelineEntry
  first: boolean
  selected: boolean
  onSelect: () => void
}) {
  return (
    <li>
      {entry.gap_before_seconds > 0 && !first && (
        <div className="py-0.5 pl-6 text-[10px] text-zinc-600">{entry.gap_before_seconds}s gap</div>
      )}
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={`flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left text-[11px] ${
          selected ? 'border-violet-600 bg-violet-950/30' : 'border-zinc-800 bg-zinc-900/40 hover:bg-zinc-800/40'
        }`}
      >
        <span className="w-12 flex-shrink-0 font-mono text-[10px] text-zinc-600">
          {formatSeconds(entry.start_seconds)}
        </span>
        <span className="flex-1 truncate text-zinc-200">{entry.shot_title}</span>
        {entry.transition_in.kind !== 'cut' && (
          <span className="rounded bg-zinc-800 px-1 py-0.5 text-[9px] text-zinc-400">
            in: {TRANSITION_LABELS[entry.transition_in.kind]}
          </span>
        )}
        {entry.transition_out.kind !== 'cut' && (
          <span className="rounded bg-zinc-800 px-1 py-0.5 text-[9px] text-zinc-400">
            out: {TRANSITION_LABELS[entry.transition_out.kind]}
          </span>
        )}
        <span className={`text-[10px] ${entry.has_render ? 'text-emerald-400' : 'text-zinc-600'}`}>
          {entry.has_render ? 'rendered' : entry.status}
        </span>
        <span className="w-12 flex-shrink-0 text-right font-mono text-[10px] text-zinc-500">
          {entry.duration_seconds}s
        </span>
      </button>
    </li>
  )
}

function ShotEdits({
  entry,
  busy,
  scenes,
  onRun,
}: {
  entry: TimelineEntry
  busy: string
  scenes: { id: string; title: string }[]
  onRun: (action: TimelineActionName, params: Record<string, unknown>, label: string) => Promise<void>
}) {
  const [duration, setDuration] = useState(entry.duration_seconds)
  const [gap, setGap] = useState(entry.gap_before_seconds)

  useEffect(() => {
    setDuration(entry.duration_seconds)
    setGap(entry.gap_before_seconds)
  }, [entry.shot_id, entry.duration_seconds, entry.gap_before_seconds])

  const otherScenes = scenes.filter(
    (scene, index, all) => scene.id !== entry.scene_id && all.findIndex(s => s.id === scene.id) === index,
  )

  return (
    <div className="space-y-2 rounded border border-violet-900/50 bg-violet-950/10 p-2">
      <p className="text-[11px] text-zinc-300">
        <span className="text-zinc-500">Editing</span> {entry.shot_title}
      </p>

      <div className="flex flex-wrap gap-1.5">
        <Action
          icon={<Scissors className="h-3 w-3" />}
          label="Split"
          title="Cut this shot in two at its midpoint"
          busy={busy === 'split'}
          onClick={() => void onRun('split_shot', { shot_id: entry.shot_id }, 'split')}
        />
        <Action
          icon={<Copy className="h-3 w-3" />}
          label="Duplicate"
          title="Copy this shot in place, without its renders"
          busy={busy === 'duplicate'}
          onClick={() => void onRun('duplicate_shot', { shot_id: entry.shot_id }, 'duplicate')}
        />
        <Action
          icon={<Clapperboard className="h-3 w-3" />}
          label="B-roll after"
          title="Insert a short cutaway after this shot, in the same location"
          busy={busy === 'broll'}
          onClick={() => void onRun('insert_broll', { after_shot_id: entry.shot_id }, 'broll')}
        />
        <Action
          icon={<Trash2 className="h-3 w-3" />}
          label="Remove"
          title="Take this shot off the timeline — undoable"
          busy={busy === 'delete'}
          danger
          onClick={() => void onRun('delete_shot', { shot_id: entry.shot_id }, 'delete')}
        />
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-[10px] text-zinc-500">
          Duration
          <div className="mt-0.5 flex items-center gap-1">
            <input
              type="number"
              min={0.5}
              max={60}
              step={0.5}
              value={duration}
              onChange={e => setDuration(Number(e.target.value))}
              aria-label="Duration in seconds"
              className="w-16 rounded border border-zinc-700 bg-zinc-800 px-1.5 py-1 text-[11px] text-zinc-200"
            />
            <button
              type="button"
              onClick={() => void onRun('trim_shot', { shot_id: entry.shot_id, duration_seconds: duration }, 'trim')}
              disabled={busy !== ''}
              title="Change this shot's length. Nothing after it moves."
              className="rounded bg-zinc-800 px-2 py-1 text-[10px] text-zinc-300 hover:bg-zinc-700 disabled:opacity-40"
            >
              Trim
            </button>
            <button
              type="button"
              onClick={() => void onRun('ripple_trim', { shot_id: entry.shot_id, duration_seconds: duration }, 'ripple')}
              disabled={busy !== ''}
              title="Change its length and hold the film's running time by taking the difference out of the gaps that follow"
              className="rounded bg-zinc-800 px-2 py-1 text-[10px] text-zinc-300 hover:bg-zinc-700 disabled:opacity-40"
            >
              Ripple
            </button>
          </div>
        </label>

        <label className="text-[10px] text-zinc-500">
          Gap before
          <div className="mt-0.5 flex items-center gap-1">
            <input
              type="number"
              min={0}
              max={30}
              step={0.25}
              value={gap}
              onChange={e => setGap(Number(e.target.value))}
              aria-label="Gap before this shot in seconds"
              className="w-16 rounded border border-zinc-700 bg-zinc-800 px-1.5 py-1 text-[11px] text-zinc-200"
            />
            <button
              type="button"
              onClick={() => void onRun('set_gap', { shot_id: entry.shot_id, gap_seconds: gap }, 'gap')}
              disabled={busy !== ''}
              className="rounded bg-zinc-800 px-2 py-1 text-[10px] text-zinc-300 hover:bg-zinc-700 disabled:opacity-40"
            >
              Set
            </button>
          </div>
        </label>

        <TransitionPicker
          label="In"
          value={entry.transition_in.kind}
          busy={busy !== ''}
          onChange={kind =>
            void onRun('set_transition', { shot_id: entry.shot_id, where: 'in', kind, duration_seconds: 0.75 }, 'transition')
          }
        />
        <TransitionPicker
          label="Out"
          value={entry.transition_out.kind}
          busy={busy !== ''}
          onChange={kind =>
            void onRun('set_transition', { shot_id: entry.shot_id, where: 'out', kind, duration_seconds: 0.75 }, 'transition')
          }
        />

        {otherScenes.length > 0 && (
          <label className="text-[10px] text-zinc-500">
            Move to scene
            <select
              value=""
              onChange={e => {
                if (!e.target.value) return
                void onRun('move_shot', { shot_id: entry.shot_id, scene_id: e.target.value }, 'move')
              }}
              disabled={busy !== ''}
              aria-label="Move this shot to another scene"
              className="mt-0.5 block rounded border border-zinc-700 bg-zinc-800 px-1.5 py-1 text-[11px] text-zinc-200 disabled:opacity-40"
            >
              <option value="">Choose…</option>
              {otherScenes.map(scene => (
                <option key={scene.id} value={scene.id}>
                  {scene.title}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    </div>
  )
}

function TransitionPicker({
  label,
  value,
  busy,
  onChange,
}: {
  label: string
  value: TransitionKind
  busy: boolean
  onChange: (kind: TransitionKind) => void
}) {
  return (
    <label className="text-[10px] text-zinc-500">
      {label}
      <select
        value={value}
        onChange={e => onChange(e.target.value as TransitionKind)}
        disabled={busy}
        aria-label={`Transition ${label.toLowerCase()}`}
        className="mt-0.5 block rounded border border-zinc-700 bg-zinc-800 px-1.5 py-1 text-[11px] text-zinc-200 disabled:opacity-40"
      >
        {Object.entries(TRANSITION_LABELS).map(([kind, name]) => (
          <option key={kind} value={kind}>
            {name}
          </option>
        ))}
      </select>
    </label>
  )
}

function Action({
  icon,
  label,
  title,
  busy,
  disabled,
  danger,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  title: string
  busy: boolean
  disabled?: boolean
  danger?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || disabled}
      title={title}
      className={`flex items-center gap-1 rounded border px-2 py-1 text-[10px] disabled:opacity-40 ${
        danger
          ? 'border-zinc-800 text-zinc-400 hover:border-red-900 hover:bg-red-950/40 hover:text-red-300'
          : 'border-zinc-700 text-zinc-300 hover:bg-zinc-800'
      }`}
    >
      {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : icon}
      {label}
    </button>
  )
}
