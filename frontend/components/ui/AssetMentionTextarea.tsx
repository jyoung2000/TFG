/** Textarea with @-mention autocomplete for style-guide assets, plus chips for what is referenced. */

import { useMemo, useRef, useState } from 'react'
import { filterAssets, findMentions, insertMention, mentionQuery } from '../../lib/assetMentions'

export interface MentionAsset { id: string; name: string; kind: string; thumbnailUrl?: string }

interface Props {
  value: string
  onChange: (value: string) => void
  assets: MentionAsset[]
  placeholder?: string
  className?: string
  rows?: number
  disabled?: boolean
  'data-testid'?: string
  'aria-label'?: string
}

function Thumb({ url, className }: { url?: string; className: string }) {
  return url
    ? <img src={url} alt="" className={className + ' object-cover'} />
    : <span className={className + ' bg-zinc-800'} />
}

export function AssetMentionTextarea({ value, onChange, assets, placeholder, className, rows, disabled, ...rest }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const [caret, setCaret] = useState(0)
  const [active, setActive] = useState(0)
  const [dismissed, setDismissed] = useState(false)
  const testId = rest['data-testid']

  const token = dismissed ? null : mentionQuery(value, caret)
  const query = token?.query
  const options = useMemo(() => (query === undefined ? [] : filterAssets(assets, query)), [assets, query])
  const open = token !== null && options.length > 0
  const mentioned = useMemo(() => {
    const names = findMentions(value, assets.map(a => a.name))
    return names.map(n => assets.find(a => a.name === n)).filter((a): a is MentionAsset => !!a)
  }, [value, assets])

  const pick = (asset: MentionAsset) => {
    if (!token) return
    const next = insertMention(value, token.start, caret, asset.name)
    onChange(next.text)
    setCaret(next.caret)
    setActive(0)
    // Restore the caret once React has applied the new value.
    requestAnimationFrame(() => {
      ref.current?.focus()
      ref.current?.setSelectionRange(next.caret, next.caret)
    })
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!open) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(i => (i + 1) % options.length) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(i => (i - 1 + options.length) % options.length) }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pick(options[Math.min(active, options.length - 1)]) }
    else if (e.key === 'Escape') { e.preventDefault(); setDismissed(true) }
  }

  return (
    <div className="relative">
      <textarea
        ref={ref}
        className={className}
        value={value}
        rows={rows}
        disabled={disabled}
        placeholder={placeholder}
        aria-label={rest['aria-label']}
        data-testid={testId}
        onChange={e => { onChange(e.target.value); setCaret(e.target.selectionStart); setActive(0); setDismissed(false) }}
        onSelect={e => setCaret(e.currentTarget.selectionStart)}
        onKeyDown={onKeyDown}
        onBlur={() => setDismissed(true)}
        onFocus={() => setDismissed(false)}
      />
      {open && (
        <ul role="listbox" data-testid={testId ? `${testId}-mentions` : undefined}
          className="absolute left-0 right-0 z-20 mt-1 max-h-48 overflow-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-lg">
          {options.map((a, i) => (
            <li key={a.id} role="option" aria-selected={i === active}
              // mousedown, not click: the textarea blur would otherwise close the list first.
              onMouseDown={e => { e.preventDefault(); pick(a) }}
              onMouseEnter={() => setActive(i)}
              className={'flex items-center gap-2 px-2 py-1 cursor-pointer text-xs ' + (i === active ? 'bg-zinc-800 text-white' : 'text-zinc-300')}>
              <Thumb url={a.thumbnailUrl} className="h-6 w-6 rounded shrink-0" />
              <span className="flex-1 truncate">{a.name}</span>
              <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-zinc-400">{a.kind}</span>
            </li>
          ))}
        </ul>
      )}
      {mentioned.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1" data-testid={testId ? `${testId}-chips` : undefined}>
          {mentioned.map(a => (
            <span key={a.id} title={`References ${a.name} (${a.kind}) from your style guides`}
              className="inline-flex items-center gap-1 rounded-full bg-violet-900/40 py-0.5 pl-0.5 pr-2 text-[10px] text-violet-200">
              <Thumb url={a.thumbnailUrl} className="h-4 w-4 rounded-full" />
              {a.name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
