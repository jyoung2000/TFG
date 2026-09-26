import { useEffect } from 'react'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'

export interface LightboxItem {
  url: string
  kind: 'image' | 'video'
  label?: string
  /** Optional caption shown under the media (prompt, path, metrics). */
  caption?: string
}

interface LightboxProps {
  items: LightboxItem[]
  index: number
  onClose: () => void
  onIndexChange?: (index: number) => void
}

/**
 * Full-screen viewer shared by the film asset gallery, History and Reproduce.
 * Keyboard: Escape closes, ←/→ move between items. Media is shown at its
 * natural size (contained), never CSS-scaled, so nothing blurs.
 */
export function Lightbox({ items, index, onClose, onIndexChange }: LightboxProps) {
  const item = items[index]
  const canPrev = index > 0
  const canNext = index < items.length - 1

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      else if (event.key === 'ArrowLeft' && canPrev) onIndexChange?.(index - 1)
      else if (event.key === 'ArrowRight' && canNext) onIndexChange?.(index + 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, canPrev, canNext, onClose, onIndexChange])

  if (!item) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={item.label ?? 'Media preview'}
      className="fixed inset-0 z-[100] bg-black/90 flex flex-col"
      onClick={onClose}
      data-testid="lightbox"
    >
      <div className="flex items-center justify-between px-4 py-2 text-zinc-300 text-xs" onClick={e => e.stopPropagation()}>
        <span className="truncate">{item.label ?? ''}{items.length > 1 ? `  ·  ${index + 1} / ${items.length}` : ''}</span>
        <button onClick={onClose} aria-label="Close preview" className="p-1.5 rounded hover:bg-zinc-800 text-zinc-300 hover:text-white">
          <X className="h-5 w-5" />
        </button>
      </div>
      <div className="flex-1 min-h-0 flex items-center justify-center relative px-12" onClick={e => e.stopPropagation()}>
        {canPrev && (
          <button
            onClick={() => onIndexChange?.(index - 1)}
            aria-label="Previous"
            className="absolute left-2 p-2 rounded-full bg-zinc-900/80 text-zinc-200 hover:bg-zinc-800"
          >
            <ChevronLeft className="h-6 w-6" />
          </button>
        )}
        {item.kind === 'video' ? (
          <video src={item.url} controls autoPlay loop playsInline className="max-h-full max-w-full rounded" />
        ) : (
          <img src={item.url} alt={item.label ?? ''} className="max-h-full max-w-full object-contain rounded" />
        )}
        {canNext && (
          <button
            onClick={() => onIndexChange?.(index + 1)}
            aria-label="Next"
            className="absolute right-2 p-2 rounded-full bg-zinc-900/80 text-zinc-200 hover:bg-zinc-800"
          >
            <ChevronRight className="h-6 w-6" />
          </button>
        )}
      </div>
      {item.caption && (
        <p className="px-4 py-3 text-xs text-zinc-400 whitespace-pre-wrap max-h-32 overflow-y-auto" onClick={e => e.stopPropagation()}>
          {item.caption}
        </p>
      )}
    </div>
  )
}
