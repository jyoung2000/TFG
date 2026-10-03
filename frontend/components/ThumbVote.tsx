import { useEffect, useState, useSyncExternalStore } from 'react'
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { nextVote, tasteStore, type TasteTarget, type Vote } from '../lib/taste'

interface ThumbVoteProps {
  target: TasteTarget
  /** "overlay" sits on a picture; "inline" sits in a row of text. */
  variant?: 'overlay' | 'inline'
  className?: string
}

/**
 * Thumbs up / thumbs down on anything the app made (lib/taste.ts): click a
 * thumb to grade, click it again to take the grade back.
 */
export function ThumbVote({ target, variant = 'inline', className = '' }: ThumbVoteProps) {
  useEffect(() => { void tasteStore.load() }, [])
  useSyncExternalStore(tasteStore.subscribe, tasteStore.version)
  const current = tasteStore.get(target.kind, target.subject)
  const [error, setError] = useState('')
  const click = (clicked: Vote) => (event: React.MouseEvent) => {
    event.stopPropagation()
    setError('')
    tasteStore.set(target, nextVote(current, clicked)).catch(e => setError(String(e)))
  }
  const base = variant === 'overlay' ? 'p-1 rounded-md bg-black/60 hover:bg-black/80' : 'p-1 rounded hover:bg-zinc-800'
  const label = target.kind === 'style_guide' ? 'style guide image' : target.kind
  return (
    <span className={`inline-flex items-center gap-0.5 ${className}`} data-testid="thumb-vote" data-vote={current} title={error || undefined}>
      <button type="button" onClick={click(1)} aria-pressed={current === 1} aria-label={`Thumbs up this ${label}`} className={`${base} ${current === 1 ? 'text-emerald-400' : 'text-zinc-400 hover:text-emerald-300'}`} data-testid="thumb-up">
        <ThumbsUp className={`h-3.5 w-3.5 ${current === 1 ? 'fill-current' : ''}`} />
      </button>
      <button type="button" onClick={click(-1)} aria-pressed={current === -1} aria-label={`Thumbs down this ${label}`} className={`${base} ${current === -1 ? 'text-red-400' : 'text-zinc-400 hover:text-red-300'}`} data-testid="thumb-down">
        <ThumbsDown className={`h-3.5 w-3.5 ${current === -1 ? 'fill-current' : ''}`} />
      </button>
    </span>
  )
}
