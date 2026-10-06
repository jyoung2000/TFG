import { useEffect, useRef, useState } from 'react'
import { Lightbox, type LightboxItem } from './Lightbox'
import { nextFrame, type MediaRef } from '../lib/hoverGallery'

export type MediaResolver = (ref: Pick<MediaRef, 'path' | 'runId' | 'datasetId'>) => Promise<string>

/** How long each picture shows while the mouse is over a thumbnail. */
const FRAME_MS = 900

interface HoverGalleryProps {
  /** The row's pictures / videos (lib/hoverGallery.ts); the first shows at rest. */
  items: MediaRef[]
  resolve: MediaResolver
  alt: string
  /** Classes for the frame (size, rounding); the media fills it. */
  className?: string
  /** Classes for the media itself (object-fit and position). */
  mediaClassName?: string
  /** Click opens the full-screen viewer on the picture showing. Omit inside a row that is itself a button. */
  onOpen?: (index: number) => void
  /** Shown when there is nothing to show. */
  fallback?: React.ReactNode
  testId?: string
}

/**
 * A thumbnail that walks its row's pictures while the mouse is over it, plays
 * a video silently, and opens the full-screen viewer on click.
 */
export function HoverGallery({ items, resolve, alt, className = '', mediaClassName = 'object-cover', onOpen, fallback = null, testId = 'hover-gallery' }: HoverGalleryProps) {
  const [urls, setUrls] = useState<Record<string, string>>({})
  const [hovered, setHovered] = useState(false)
  const [index, setIndex] = useState(0)
  const key = items.map(i => `${i.runId ?? i.datasetId ?? ''}:${i.path}`).join('|')
  const resolveRef = useRef(resolve)
  resolveRef.current = resolve

  // The picture at rest loads at once; the rest only when the mouse arrives.
  useEffect(() => {
    let cancelled = false
    const wanted = hovered ? items : items.slice(0, 1)
    wanted.forEach(item => {
      for (const path of [item.kind === 'video' && !hovered ? '' : item.path, item.poster ?? ''].filter(Boolean)) {
        const id = `${item.runId ?? item.datasetId ?? ''}:${path}`
        resolveRef.current({ path, runId: item.runId, datasetId: item.datasetId })
          .then(url => { if (!cancelled) setUrls(known => (known[id] === url ? known : { ...known, [id]: url })) })
          .catch(() => undefined)
      }
    })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, hovered])

  useEffect(() => { setIndex(0) }, [key])
  useEffect(() => {
    if (!hovered) { setIndex(0); return }
    if (items.length < 2) return
    const timer = window.setInterval(() => setIndex(current => (items[current]?.kind === 'video' ? current : nextFrame(current, items.length))), FRAME_MS)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hovered, key])

  const urlOf = (item: MediaRef | undefined, path: string | undefined) => (item && path ? urls[`${item.runId ?? item.datasetId ?? ''}:${path}`] : undefined)
  const item = items[Math.min(index, Math.max(0, items.length - 1))]
  // While the next picture loads, keep showing the first rather than a hole.
  const still = item?.kind === 'video' ? urlOf(item, item.poster) : urlOf(item, item?.path) ?? urlOf(items[0], items[0]?.kind === 'video' ? items[0]?.poster : items[0]?.path)
  const video = hovered && item?.kind === 'video' ? urlOf(item, item.path) : undefined
  if (!item || (!still && !video && !(item.kind === 'video'))) return <>{fallback}</>

  const media = video
    ? <video src={video} poster={still} muted autoPlay loop playsInline className={`w-full h-full ${mediaClassName}`} data-testid="hover-video" />
    : still
      ? <img src={still} alt={alt} loading="lazy" className={`w-full h-full ${mediaClassName}`} />
      : <div className="w-full h-full bg-zinc-900" />
  const dots = hovered && items.length > 1 && (
    <span className="absolute bottom-0.5 inset-x-0 flex justify-center gap-0.5 pointer-events-none" aria-hidden="true">
      {items.slice(0, 8).map((_, i) => <span key={i} className={`h-1 w-1 rounded-full ${i === index ? 'bg-white' : 'bg-white/40'}`} />)}
    </span>
  )
  const frame = `relative overflow-hidden ${className}`
  const hover = { onMouseEnter: () => setHovered(true), onMouseLeave: () => setHovered(false) }
  if (!onOpen) return <span className={`block ${frame}`} {...hover} data-testid={testId} data-frame={index}>{media}{dots}</span>
  return (
    <button type="button" className={`block cursor-zoom-in ${frame}`} {...hover} onClick={event => { event.stopPropagation(); onOpen(index) }}
      aria-label={`Open ${alt} full screen`} data-testid={testId} data-frame={index}>
      {media}{dots}
    </button>
  )
}

interface MediaLightboxProps {
  items: MediaRef[]
  resolve: MediaResolver
  index: number
  caption?: string
  onClose: () => void
  onIndexChange: (index: number) => void
}

/** The full-screen viewer over a row's pictures: resolves them, then shows components/Lightbox. */
export function MediaLightbox({ items, resolve, index, caption, onClose, onIndexChange }: MediaLightboxProps) {
  const [resolved, setResolved] = useState<LightboxItem[] | null>(null)
  const key = items.map(i => `${i.runId ?? i.datasetId ?? ''}:${i.path}`).join('|')
  useEffect(() => {
    let cancelled = false
    void Promise.all(items.map(async (item): Promise<LightboxItem> => ({
      url: await resolve({ path: item.path, runId: item.runId, datasetId: item.datasetId }).catch(() => ''),
      kind: item.kind,
      label: item.label ?? item.path.split(/[\\/]/).pop() ?? item.path,
      caption,
      path: item.path,
    }))).then(all => { if (!cancelled) setResolved(all) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  if (!resolved || resolved.length === 0) return null
  return <Lightbox items={resolved} index={Math.min(index, resolved.length - 1)} onClose={onClose} onIndexChange={onIndexChange} />
}
