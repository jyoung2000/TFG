/**
 * Shared pieces of the Assets tab: kind metadata, the per-kind detail
 * fields, palette rendering and the media-thumb hooks. Moved verbatim from
 * the old single-file AssetsPanel so grid, detail and wizard stay in sync.
 */

import { useEffect, useState } from 'react'
import { MapPin, Package, Palette, User } from 'lucide-react'
import type { LightboxItem } from '../../../components/Lightbox'
import { useFilm } from '../../../contexts/FilmContext'
import { filmMediaUrl } from '../../../lib/film-api'
import type { FilmAsset, FilmAssetKind } from '../../../types/film'

export const KIND_META: Record<FilmAssetKind, { label: string; plural: string; icon: React.ReactNode; color: string; gradient: string }> = {
  character: { label: 'Character', plural: 'Characters', icon: <User className="h-4 w-4" />, color: 'bg-amber-600/20 text-amber-300', gradient: 'from-amber-900/40 to-zinc-950' },
  location: { label: 'Location', plural: 'Locations', icon: <MapPin className="h-4 w-4" />, color: 'bg-emerald-600/20 text-emerald-300', gradient: 'from-emerald-900/40 to-zinc-950' },
  prop: { label: 'Prop', plural: 'Props', icon: <Package className="h-4 w-4" />, color: 'bg-sky-600/20 text-sky-300', gradient: 'from-sky-900/40 to-zinc-950' },
  style: { label: 'Style', plural: 'Styles', icon: <Palette className="h-4 w-4" />, color: 'bg-fuchsia-600/20 text-fuchsia-300', gradient: 'from-fuchsia-900/40 to-zinc-950' },
}

export const inputClass = 'w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600'

export function paletteSwatch(label: string): string {
  const value = label.trim().toLowerCase()
  if (/^#[0-9a-f]{3,8}$/i.test(value) || /^rgba?\(/i.test(value)) return value
  if (value.includes('brass') || value.includes('gold') || value.includes('amber')) return '#b88a42'
  if (value.includes('cream') || value.includes('ivory')) return '#eee2bd'
  if (value.includes('charcoal') || value.includes('black')) return '#383838'
  if (value.includes('white')) return '#efefef'
  if (value.includes('blue') || value.includes('navy')) return '#4779a8'
  if (value.includes('green') || value.includes('olive')) return '#668056'
  if (value.includes('red') || value.includes('rust')) return '#a94d3d'
  if (value.includes('brown') || value.includes('tan')) return '#94704f'
  if (value.includes('gray') || value.includes('grey') || value.includes('silver')) return '#92969a'
  return '#777777'
}

export const KIND_FIELDS: Record<FilmAssetKind, { key: keyof FilmAsset; label: string }[]> = {
  character: [
    { key: 'description', label: 'Identity / role' }, { key: 'appearance', label: 'Appearance' },
    { key: 'wardrobe', label: 'Wardrobe' }, { key: 'accessories', label: 'Accessories' },
    { key: 'continuity_notes', label: 'Continuity notes' },
  ],
  location: [
    { key: 'description', label: 'Description' }, { key: 'environment', label: 'Environment' },
    { key: 'lighting', label: 'Lighting' }, { key: 'atmosphere', label: 'Atmosphere' },
    { key: 'time_of_day', label: 'Time of day' }, { key: 'continuity_notes', label: 'Continuity notes' },
  ],
  prop: [
    { key: 'description', label: 'Description' }, { key: 'prop_details', label: 'Details' },
    { key: 'continuity_notes', label: 'Continuity notes' },
  ],
  style: [
    { key: 'description', label: 'Description' }, { key: 'style_prompt', label: 'Style prompt (appended to every shot)' },
  ],
}

export type ThumbState = { status: 'loading' } | { status: 'ready'; url: string } | { status: 'error'; message: string }

/**
 * Resolve a film-project media path to an authenticated URL. Keyed on the
 * project *id* (not the whole film object) so a store refresh does not refetch
 * every thumbnail, and errors surface instead of leaving a skeleton forever.
 */
export function useFilmMediaUrl(path: string | undefined): ThumbState {
  const { film } = useFilm()
  const filmId = film?.id
  const [state, setState] = useState<ThumbState>({ status: 'loading' })
  useEffect(() => {
    let cancelled = false
    if (!filmId || !path) { setState({ status: 'error', message: 'No image' }); return }
    setState({ status: 'loading' })
    filmMediaUrl(filmId, path)
      .then(url => { if (!cancelled) setState({ status: 'ready', url }) })
      .catch((err: unknown) => { if (!cancelled) setState({ status: 'error', message: err instanceof Error ? err.message : String(err) }) })
    return () => { cancelled = true }
  }, [filmId, path])
  return state
}

export function ThumbError({ className, message }: { className: string; message: string }) {
  return (
    <div role="img" aria-label={`Image unavailable: ${message}`} title={message}
      className={className + ' flex items-center justify-center text-[10px] text-red-300 bg-red-950/30 border border-red-900/50 rounded'}>
      unavailable
    </div>
  )
}

export function GalleryThumb({ path, onOpen, size = 'w-16 h-16' }: { path: string; onOpen: () => void; size?: string }) {
  const state = useFilmMediaUrl(path)
  const cls = size + ' rounded border border-zinc-800'
  if (state.status === 'loading') return <div className={cls + ' bg-zinc-900 animate-pulse'} />
  if (state.status === 'error') return <ThumbError className={cls} message={state.message} />
  return (
    <button type="button" onClick={onOpen} className="cursor-zoom-in shrink-0" aria-label={`Open reference image ${path.split('/').pop() ?? ''}`}>
      <img src={state.url} alt="" loading="lazy" className={cls + ' object-cover'} title={`Reference image ${path.split('/').pop() ?? ''}`} />
    </button>
  )
}

/** Resolved URLs for every reference image of an asset, for the lightbox. */
export function useReferenceUrls(asset: FilmAsset | null): LightboxItem[] {
  const { film } = useFilm()
  const filmId = film?.id
  const paths = asset?.reference_images ?? []
  const key = paths.join('\n')
  const [items, setItems] = useState<LightboxItem[]>([])
  useEffect(() => {
    let cancelled = false
    if (!filmId || !paths.length) { setItems([]); return }
    void Promise.all(paths.map(async (p): Promise<LightboxItem | null> => {
      try { return { url: await filmMediaUrl(filmId, p), kind: 'image', label: p.split('/').pop() ?? p } }
      catch { return null }
    })).then(resolved => { if (!cancelled) setItems(resolved.filter((x): x is LightboxItem => x !== null)) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filmId, key])
  return items
}

/** Read a picked file as a data URL (what `addAssetReference` expects). */
export function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('Could not read the file'))
    reader.readAsDataURL(file)
  })
}
