import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Archive,
  ArchiveRestore,
  Copy,
  Library,
  Loader2,
  Search,
  Star,
  Trash2,
  Wand2,
  X,
} from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { libraryPreviewUrl, shotLibraryApi } from '../../lib/shot-library-api'
import { SORT_LABELS, type LibraryShot, type LibrarySort } from '../../types/shot-library'

/**
 * Settings → Shot Library, and the picker inside a film.
 *
 * Every item here is a copy: the settings were snapshotted and the preview was
 * copied into the library's own directory when it was saved. That is why an
 * item keeps working after the take it came from is deleted, and why applying
 * one never ties the new shot back to it. The lineage line says where it came
 * from as a record, not as a link.
 */
export function ShotLibraryPanel({
  onApply,
  compact = false,
}: {
  /** Given when the library is opened from inside a film, to use an item. */
  onApply?: (item: LibraryShot) => Promise<void> | void
  compact?: boolean
}) {
  const [items, setItems] = useState<LibraryShot[]>([])
  const [tags, setTags] = useState<Record<string, number>>({})
  const [query, setQuery] = useState('')
  const [activeTags, setActiveTags] = useState<string[]>([])
  const [favouritesOnly, setFavouritesOnly] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [sort, setSort] = useState<LibrarySort>('recent')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [editing, setEditing] = useState<LibraryShot | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const listing = await shotLibraryApi.list({
        q: query,
        tags: activeTags,
        favorite: favouritesOnly ? true : undefined,
        archived: showArchived,
        sort,
      })
      setItems(listing.items)
      setTags(listing.tags)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read the shot library.')
    } finally {
      setLoading(false)
    }
  }, [query, activeTags, favouritesOnly, showArchived, sort])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), query ? 250 : 0)
    return () => window.clearTimeout(timer)
  }, [load, query])

  const run = async (id: string, work: () => Promise<unknown>, message: string) => {
    setBusy(id)
    setError('')
    try {
      await work()
      setNote(message)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work.')
    } finally {
      setBusy('')
    }
  }

  const remove = (item: LibraryShot) => {
    if (
      !window.confirm(
        `Delete "${item.title}" permanently? Its preview goes with it.\n\nArchiving hides it instead, and can be undone.`,
      )
    )
      return
    void run(item.id, () => shotLibraryApi.remove(item.id), `Deleted ${item.title}`)
  }

  const toggleTag = (tag: string) =>
    setActiveTags(current => (current.includes(tag) ? current.filter(t => t !== tag) : [...current, tag]))

  const tagList = useMemo(() => Object.entries(tags), [tags])

  return (
    <div className="space-y-3">
      {!compact && (
        <header>
          <div className="flex items-center gap-2">
            <Library className="h-4 w-4 text-violet-400" />
            <h3 className="text-sm font-semibold text-white">Shot Library</h3>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-zinc-500">
            Shots worth keeping, saved out of whatever film they were made for. Each one is a copy —
            settings snapshotted, preview copied — so it keeps working after the take, the shot or
            the whole project it came from is gone.
          </p>
        </header>
      )}

      {/* ---- search and filter ---- */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[180px] flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-600" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search titles, prompts, notes and tags"
            aria-label="Search the shot library"
            className="w-full rounded border border-zinc-700 bg-zinc-800 py-1.5 pl-7 pr-2 text-xs text-zinc-200"
          />
        </div>
        <button
          type="button"
          onClick={() => setFavouritesOnly(!favouritesOnly)}
          aria-pressed={favouritesOnly}
          className={`flex items-center gap-1 rounded border px-2 py-1.5 text-[11px] ${
            favouritesOnly ? 'border-amber-600 text-amber-300' : 'border-zinc-700 text-zinc-400 hover:bg-zinc-800'
          }`}
        >
          <Star className={`h-3 w-3 ${favouritesOnly ? 'fill-amber-300' : ''}`} /> Favourites
        </button>
        <button
          type="button"
          onClick={() => setShowArchived(!showArchived)}
          aria-pressed={showArchived}
          className={`flex items-center gap-1 rounded border px-2 py-1.5 text-[11px] ${
            showArchived ? 'border-violet-600 text-violet-300' : 'border-zinc-700 text-zinc-400 hover:bg-zinc-800'
          }`}
        >
          <Archive className="h-3 w-3" /> Archived
        </button>
        <select
          value={sort}
          onChange={e => setSort(e.target.value as LibrarySort)}
          aria-label="Sort the shot library"
          className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-[11px] text-zinc-300"
        >
          {Object.entries(SORT_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {tagList.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {tagList.map(([tag, count]) => (
            <button
              key={tag}
              type="button"
              onClick={() => toggleTag(tag)}
              aria-pressed={activeTags.includes(tag)}
              className={`rounded-full border px-2 py-0.5 text-[10px] ${
                activeTags.includes(tag)
                  ? 'border-violet-500 bg-violet-500/20 text-violet-200'
                  : 'border-zinc-700 text-zinc-400 hover:bg-zinc-800'
              }`}
            >
              {tag} <span className="text-zinc-600">{count}</span>
            </button>
          ))}
          {activeTags.length > 0 && (
            <button
              type="button"
              onClick={() => setActiveTags([])}
              className="flex items-center gap-1 rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] text-zinc-500 hover:bg-zinc-800"
            >
              <X className="h-2.5 w-2.5" /> Clear
            </button>
          )}
        </div>
      )}

      {error && (
        <p className="rounded border border-red-900/60 bg-red-950/40 px-2 py-1.5 text-[11px] text-red-300">{error}</p>
      )}
      {note && !error && <p className="text-[11px] text-zinc-500">{note}</p>}

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading…
        </div>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-zinc-800 px-3 py-6 text-center text-xs text-zinc-500">
          {showArchived
            ? 'Nothing archived.'
            : query || activeTags.length || favouritesOnly
              ? 'Nothing matches that.'
              : 'Nothing saved yet. Save a shot from its drawer and it appears here, usable in any film.'}
        </p>
      ) : (
        <div className={`grid gap-2 ${compact ? 'sm:grid-cols-2' : 'sm:grid-cols-2 lg:grid-cols-3'}`}>
          {items.map(item => (
            <LibraryCard
              key={item.id}
              item={item}
              busy={busy === item.id}
              onApply={onApply}
              onEdit={() => setEditing(item)}
              onFavourite={() =>
                void run(
                  item.id,
                  () => shotLibraryApi.update(item.id, { favorite: !item.favorite }),
                  item.favorite ? 'Removed from favourites' : 'Added to favourites',
                )
              }
              onDuplicate={() => void run(item.id, () => shotLibraryApi.duplicate(item.id), 'Duplicated')}
              onArchive={() =>
                void run(
                  item.id,
                  () => (item.archived ? shotLibraryApi.restore(item.id) : shotLibraryApi.archive(item.id)),
                  item.archived ? 'Restored' : 'Archived',
                )
              }
              onDelete={() => remove(item)}
            />
          ))}
        </div>
      )}

      {editing && (
        <EditDialog
          item={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null)
            await load()
          }}
        />
      )}
    </div>
  )
}

function LibraryCard({
  item,
  busy,
  onApply,
  onEdit,
  onFavourite,
  onDuplicate,
  onArchive,
  onDelete,
}: {
  item: LibraryShot
  busy: boolean
  onApply?: (item: LibraryShot) => Promise<void> | void
  onEdit: () => void
  onFavourite: () => void
  onDuplicate: () => void
  onArchive: () => void
  onDelete: () => void
}) {
  const [preview, setPreview] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    if (item.preview_kind === 'none') {
      setPreview(null)
      return
    }
    void libraryPreviewUrl(item).then(url => {
      if (!cancelled) setPreview(url)
    })
    return () => {
      cancelled = true
    }
  }, [item])

  return (
    <article className="flex flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900/40">
      <div className="relative aspect-video bg-black">
        {preview && item.preview_kind === 'video' ? (
          <video src={preview} controls playsInline preload="metadata" className="h-full w-full object-contain" />
        ) : preview ? (
          <img src={preview} alt="" className="h-full w-full object-contain" />
        ) : (
          <div className="flex h-full items-center justify-center text-[10px] text-zinc-700">No preview</div>
        )}
        <button
          type="button"
          onClick={onFavourite}
          aria-label={item.favorite ? `Remove ${item.title} from favourites` : `Add ${item.title} to favourites`}
          className="absolute right-1.5 top-1.5 rounded bg-black/60 p-1 text-zinc-300 hover:text-amber-300"
        >
          <Star className={`h-3 w-3 ${item.favorite ? 'fill-amber-300 text-amber-300' : ''}`} />
        </button>
      </div>

      <div className="flex-1 space-y-1.5 p-2">
        <div className="flex items-start gap-1.5">
          <h4 className="flex-1 text-xs font-medium text-white">{item.title}</h4>
          {item.rating > 0 && <span className="text-[10px] text-amber-300">{'★'.repeat(item.rating)}</span>}
        </div>
        {item.notes && <p className="text-[10px] leading-relaxed text-zinc-500">{item.notes}</p>}
        <p className="line-clamp-2 text-[10px] leading-relaxed text-zinc-400">{item.visual_prompt}</p>
        <div className="flex flex-wrap gap-1">
          {item.tags.map(tag => (
            <span key={tag} className="rounded-full bg-zinc-800 px-1.5 py-0.5 text-[9px] text-zinc-400">
              {tag}
            </span>
          ))}
        </div>
        {/* Where it came from — a record, not a link. The project may be gone. */}
        <p className="text-[9px] text-zinc-600">
          From {item.lineage.project_name || item.lineage.project_id || 'an earlier film'}
          {item.lineage.shot_title ? ` · ${item.lineage.shot_title}` : ''}
          {item.model ? ` · ${item.model}` : ''}
          {item.used_count > 0 ? ` · used ${item.used_count}×` : ''}
        </p>
      </div>

      <div className="flex flex-wrap gap-1 border-t border-zinc-800 p-1.5">
        {onApply && !item.archived && (
          <button
            type="button"
            onClick={() => void onApply(item)}
            disabled={busy}
            className="flex items-center gap-1 rounded bg-violet-600/80 px-2 py-1 text-[10px] text-white hover:bg-violet-600 disabled:opacity-40"
          >
            <Wand2 className="h-2.5 w-2.5" /> Use
          </button>
        )}
        <button
          type="button"
          onClick={onEdit}
          disabled={busy}
          className="rounded bg-zinc-800 px-2 py-1 text-[10px] text-zinc-300 hover:bg-zinc-700 disabled:opacity-40"
        >
          Edit
        </button>
        <button
          type="button"
          onClick={onDuplicate}
          disabled={busy}
          aria-label={`Duplicate ${item.title}`}
          className="rounded bg-zinc-800 p-1 text-zinc-400 hover:bg-zinc-700 disabled:opacity-40"
        >
          <Copy className="h-2.5 w-2.5" />
        </button>
        <button
          type="button"
          onClick={onArchive}
          disabled={busy}
          aria-label={item.archived ? `Restore ${item.title}` : `Archive ${item.title}`}
          title={item.archived ? 'Bring it back' : 'Hide it — this can be undone'}
          className="rounded bg-zinc-800 p-1 text-zinc-400 hover:bg-zinc-700 disabled:opacity-40"
        >
          {item.archived ? <ArchiveRestore className="h-2.5 w-2.5" /> : <Archive className="h-2.5 w-2.5" />}
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={busy}
          aria-label={`Delete ${item.title}`}
          title="Delete permanently — archiving hides it instead and can be undone"
          className="rounded bg-zinc-800 p-1 text-zinc-500 hover:bg-red-950 hover:text-red-300 disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <Trash2 className="h-2.5 w-2.5" />}
        </button>
      </div>
    </article>
  )
}

function EditDialog({
  item,
  onClose,
  onSaved,
}: {
  item: LibraryShot
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [title, setTitle] = useState(item.title)
  const [notes, setNotes] = useState(item.notes)
  const [tags, setTags] = useState(item.tags.join(', '))
  const [rating, setRating] = useState(item.rating)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await shotLibraryApi.update(item.id, {
        title,
        notes,
        tags: tags.split(',').map(t => t.trim()).filter(Boolean),
        rating,
      })
      await onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save that.')
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-label="Edit library item">
      <div className="w-full max-w-md space-y-3 rounded-lg border border-zinc-700 bg-zinc-900 p-4">
        <h3 className="text-sm font-semibold text-white">Edit library item</h3>
        {error && <p className="text-[11px] text-red-300">{error}</p>}
        <label className="block text-[11px] text-zinc-400">
          Title
          <input
            value={title}
            onChange={e => setTitle(e.target.value)}
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-200"
          />
        </label>
        <label className="block text-[11px] text-zinc-400">
          Notes
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={3}
            placeholder="What made this one work"
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-200"
          />
        </label>
        <label className="block text-[11px] text-zinc-400">
          Tags, comma separated
          <input
            value={tags}
            onChange={e => setTags(e.target.value)}
            placeholder="night, interior, hero"
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-200"
          />
        </label>
        <div className="flex items-center gap-2 text-[11px] text-zinc-400">
          Rating
          {[1, 2, 3, 4, 5].map(value => (
            <button
              key={value}
              type="button"
              onClick={() => setRating(rating === value ? 0 : value)}
              aria-label={`Rate ${value} of 5`}
              className={value <= rating ? 'text-amber-300' : 'text-zinc-700 hover:text-zinc-500'}
            >
              <Star className={`h-3.5 w-3.5 ${value <= rating ? 'fill-amber-300' : ''}`} />
            </button>
          ))}
          {rating > 0 && (
            <button type="button" onClick={() => setRating(0)} className="text-zinc-600 hover:text-zinc-400">
              clear
            </button>
          )}
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded px-3 py-1.5 text-xs text-zinc-400 hover:bg-zinc-800">
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving}
            className="flex items-center gap-1.5 rounded bg-violet-600 px-3 py-1.5 text-xs text-white hover:bg-violet-500 disabled:opacity-40"
          >
            {saving && <Loader2 className="h-3 w-3 animate-spin" />} Save
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * The library inside a film: the same panel, wired so "Use" adds the item as a
 * new shot in the scene the user is looking at.
 */
export function ShotLibraryPicker({ sceneId, onApplied }: { sceneId: string; onApplied?: () => void }) {
  const { film, refresh } = useFilm()
  const [note, setNote] = useState('')

  const apply = async (item: LibraryShot) => {
    if (!film) return
    try {
      await shotLibraryApi.apply(item.id, { project_id: film.id, scene_id: sceneId })
      await refresh()
      setNote(`Added "${item.title}" to this scene`)
      onApplied?.()
    } catch (err) {
      setNote(err instanceof Error ? err.message : 'Could not use that item.')
    }
  }

  return (
    <div className="space-y-2">
      {note && <p className="text-[11px] text-zinc-400">{note}</p>}
      <ShotLibraryPanel compact onApply={apply} />
    </div>
  )
}
