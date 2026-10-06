/**
 * Save a style from an image (user, 2026-10-05: "Add a new option on the home menu to
 * save style from image"): the vision AI reverse-engineers the art style from 1-6
 * pictures (medium, line work, shading, palette); the image and video generators then
 * draw in it (components/StylePicker.tsx).
 */
import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, ImagePlus, Loader2, Palette, Trash2, X } from 'lucide-react'
import { useProjects } from '../contexts/ProjectContext'
import { StyleThumb } from '../components/StylePicker'
import { stylesApi, type SavedStyle } from '../lib/styles-api'

const MAX_PICTURES = 6

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the file'))
    reader.readAsDataURL(file)
  })
}

export function StyleLibrary() {
  const { goHome, setCurrentView } = useProjects()
  const [styles, setStyles] = useState<SavedStyle[]>([])
  const [name, setName] = useState('')
  const [pictures, setPictures] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')
  const [saved, setSaved] = useState<SavedStyle | null>(null)

  const refresh = useCallback(async () => {
    try { setStyles(await stylesApi.list()) } catch (e) { setNote('Could not load styles: ' + (e instanceof Error ? e.message : String(e))) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const addPictures = useCallback(async (files: FileList | null) => {
    if (!files) return
    const read = await Promise.all(Array.from(files).filter(f => f.type.startsWith('image/')).map(readAsDataUrl))
    setPictures(prev => [...prev, ...read].slice(0, MAX_PICTURES))
  }, [])

  const save = useCallback(async () => {
    if (!name.trim() || pictures.length === 0) return
    setSaving(true); setNote('Reading the art style…'); setSaved(null)
    try {
      const style = await stylesApi.create(name.trim(), pictures)
      setSaved(style); setName(''); setPictures([]); setNote('')
      await refresh()
    } catch (e) { setNote('Failed: ' + (e instanceof Error ? e.message : String(e))) }
    finally { setSaving(false) }
  }, [name, pictures, refresh])

  const remove = useCallback(async (style: SavedStyle) => {
    if (!window.confirm(`Delete the style "${style.name}"? Its pictures are deleted.`)) return
    try { await stylesApi.remove(style.id); if (saved?.id === style.id) setSaved(null); await refresh() }
    catch (e) { setNote('Failed: ' + (e instanceof Error ? e.message : String(e))) }
  }, [refresh, saved])

  return (
    <div className="h-full overflow-y-auto bg-zinc-950 text-white" data-testid="style-library">
      <header className="flex items-center gap-3 border-b border-zinc-800 px-6 py-4">
        <button onClick={goHome} aria-label="Back to home" className="rounded p-1.5 text-zinc-400 hover:bg-zinc-800"><ArrowLeft className="h-4 w-4" /></button>
        <Palette className="h-5 w-5 text-fuchsia-300" />
        <h1 className="text-lg font-semibold">Styles</h1>
        <div className="flex-1" />
        <button onClick={() => setCurrentView('playground')} className="rounded bg-zinc-800 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-700">Open Playground</button>
      </header>

      <main className="mx-auto max-w-4xl space-y-8 px-6 py-6">
        <section className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4" aria-labelledby="save-style-heading">
          <h2 id="save-style-heading" className="text-sm font-semibold">Save a style from an image</h2>
          <p className="text-xs text-zinc-400">
            Add 1–{MAX_PICTURES} pictures in the art style. The vision AI reads how they are drawn (medium, line work, shading, palette), never what they show.
            Pick the style in the Playground or Gen Space and images and videos are drawn in it with FLUX.1 USO (FLUX.2 Klein when USO is not installed).
          </p>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Style name, e.g. Seaside Watercolor" disabled={saving}
            className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm" data-testid="style-name" />
          <div className="flex flex-wrap gap-2">
            {pictures.map((src, i) => (
              <div key={i} className="relative">
                <img src={src} alt={`Style picture ${i + 1}`} className="h-24 w-24 rounded border border-zinc-700 object-cover" />
                <button onClick={() => setPictures(prev => prev.filter((_, j) => j !== i))} aria-label={`Remove picture ${i + 1}`}
                  className="absolute -right-1.5 -top-1.5 rounded-full bg-zinc-900 p-0.5 text-zinc-300 hover:text-white"><X className="h-3 w-3" /></button>
              </div>
            ))}
            {pictures.length < MAX_PICTURES && (
              <label className="flex h-24 w-24 cursor-pointer flex-col items-center justify-center gap-1 rounded border border-dashed border-zinc-700 text-[11px] text-zinc-400 hover:border-zinc-500">
                <ImagePlus className="h-5 w-5" /> Add image
                <input type="file" accept="image/*" multiple className="hidden" disabled={saving} data-testid="style-files"
                  onChange={e => { void addPictures(e.target.files); e.target.value = '' }} />
              </label>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => void save()} disabled={saving || !name.trim() || pictures.length === 0} data-testid="style-save"
              className="flex items-center gap-1.5 rounded bg-fuchsia-700 px-4 py-1.5 text-xs font-medium text-white hover:bg-fuchsia-600 disabled:opacity-40">
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Palette className="h-3.5 w-3.5" />} Save style
            </button>
            {note && <span className={`text-xs ${note.startsWith('Failed') || note.startsWith('Could') ? 'text-red-400' : 'text-zinc-400'}`}>{note}</span>}
          </div>
          {saved && (
            <div className="rounded border border-emerald-800/60 bg-emerald-950/30 p-3 text-xs" data-testid="style-saved">
              <p className="font-medium text-emerald-300">Saved “{saved.name}”</p>
              <p className="mt-1 text-zinc-300">{saved.style_prompt || 'No vision AI is set up (Settings → AI Director), so the pictures alone carry the style.'}</p>
              {saved.style_guide && saved.style_guide.key_traits.length > 0 && (
                <ul className="mt-2 list-disc space-y-0.5 pl-4 text-zinc-400">{saved.style_guide.key_traits.slice(0, 7).map(t => <li key={t}>{t}</li>)}</ul>
              )}
            </div>
          )}
        </section>

        <section aria-labelledby="saved-styles-heading" className="space-y-3">
          <h2 id="saved-styles-heading" className="text-sm font-semibold">Saved styles</h2>
          {styles.length === 0 ? <p className="text-xs text-zinc-500">None yet.</p> : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {styles.map(style => (
                <article key={style.id} className="flex gap-3 rounded-lg border border-zinc-800 bg-zinc-900/60 p-3" data-testid="saved-style">
                  <StyleThumb style={style} className="h-20 w-20 shrink-0 rounded" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="truncate text-sm font-medium">{style.name}</h3>
                      <span className="text-[10px] text-zinc-500">{style.images.length} picture{style.images.length === 1 ? '' : 's'}</span>
                      <div className="flex-1" />
                      <button onClick={() => void remove(style)} aria-label={`Delete style ${style.name}`} className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-red-400"><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                    <p className="mt-1 line-clamp-3 text-[11px] text-zinc-400">{style.style_prompt || 'Drawn from its pictures'}</p>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
