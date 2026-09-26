/**
 * Layout 1 — the library: header with search and "New asset", a rail of
 * kind + consistency filters, and the card grid with a ghost "New asset"
 * cell. Filters are local state; assets come from the film store.
 */

import { useMemo, useRef, useState } from 'react'
import { Plus } from 'lucide-react'
import type { FilmAsset, FilmAssetKind } from '../../../types/film'
import { assetStatus, consistencyOf } from './consistency'
import { AssetCard } from './AssetCard'
import { KIND_META } from './shared'

type ConsistencyFilter = 'locked' | 'needs-lora' | 'no-seed'
const KIND_ORDER: FilmAssetKind[] = ['character', 'location', 'prop', 'style']

const CONSISTENCY_FILTERS: { id: ConsistencyFilter; label: string; dot: string; match: (a: FilmAsset) => boolean }[] = [
  { id: 'locked', label: 'Production-locked', dot: 'bg-emerald-400', match: a => consistencyOf(a).locked },
  { id: 'needs-lora', label: 'Needs LoRA', dot: 'bg-amber-400', match: a => assetStatus(a) === 'needs-lora' },
  { id: 'no-seed', label: 'No seed lock', dot: 'bg-red-400', match: a => a.kind !== 'style' && a.seed_lock === null },
]

export function AssetGrid({ assets, onSelect, onRemove, onCreate, onOpenWizard }: {
  assets: FilmAsset[]
  onSelect: (id: string) => void
  onRemove: (asset: FilmAsset) => void
  onCreate: (kind: FilmAssetKind) => void
  onOpenWizard: () => void
}) {
  const [search, setSearch] = useState('')
  const [kindFilter, setKindFilter] = useState<FilmAssetKind | null>(null)
  const [consistencyFilter, setConsistencyFilter] = useState<ConsistencyFilter | null>(null)
  const [newMenu, setNewMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement | null>(null)

  const locked = assets.filter(a => consistencyOf(a).locked && a.kind !== 'style').length
  const visible = useMemo(() => {
    const query = search.trim().toLowerCase()
    return assets
      .filter(a => !kindFilter || a.kind === kindFilter)
      .filter(a => !consistencyFilter || CONSISTENCY_FILTERS.find(f => f.id === consistencyFilter)?.match(a))
      .filter(a => !query || `${a.name} ${a.description} ${a.lora_trigger}`.toLowerCase().includes(query))
      .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind))
  }, [assets, kindFilter, consistencyFilter, search])

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="asset-grid">
      <div className="h-14 shrink-0 border-b border-zinc-800 px-4 flex items-center gap-3">
        <h2 className="text-sm font-semibold text-white">Assets</h2>
        <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-[10px] text-zinc-400">
          {assets.length} asset{assets.length === 1 ? '' : 's'} · {locked} production-locked
        </span>
        <div className="flex-1" />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search name, description, trigger…"
          aria-label="Search assets"
          className="w-56 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600" />
        <div className="relative" ref={menuRef}>
          <button onClick={() => setNewMenu(v => !v)} data-testid="new-asset"
            className="flex items-center gap-1 px-3 py-1.5 rounded bg-violet-700 hover:bg-violet-600 text-xs font-medium text-white">
            <Plus className="h-3.5 w-3.5" /> New asset
          </button>
          {newMenu && (
            <div className="absolute right-0 top-full mt-1 z-30 w-44 rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl p-1">
              <button onClick={() => { setNewMenu(false); onOpenWizard() }} data-testid="new-asset-ai"
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-left text-xs text-violet-200 hover:bg-violet-900/40">
                ✨ Build with AI…
              </button>
              <div className="my-1 border-t border-zinc-800" />
              {KIND_ORDER.map(kind => (
                <button key={kind} onClick={() => { setNewMenu(false); onCreate(kind) }}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-left text-xs text-zinc-300 hover:bg-zinc-800">
                  <span className="text-zinc-500">{KIND_META[kind].icon}</span>{KIND_META[kind].label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-1 min-h-0">
        <div className="w-52 shrink-0 border-r border-zinc-800 bg-zinc-950/60 p-3 space-y-4 overflow-y-auto">
          <div>
            <span className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wide">Library</span>
            <div className="mt-1.5 space-y-0.5">
              <RailRow label="All assets" count={assets.length} active={kindFilter === null} onClick={() => setKindFilter(null)} />
              {KIND_ORDER.map(kind => (
                <RailRow key={kind} icon={<span className={KIND_META[kind].color.split(' ')[1]}>{KIND_META[kind].icon}</span>}
                  label={KIND_META[kind].plural} count={assets.filter(a => a.kind === kind).length}
                  active={kindFilter === kind} onClick={() => setKindFilter(kindFilter === kind ? null : kind)} />
              ))}
            </div>
          </div>
          <div>
            <span className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wide">Consistency</span>
            <div className="mt-1.5 space-y-0.5">
              {CONSISTENCY_FILTERS.map(f => (
                <RailRow key={f.id} icon={<span className={`w-1.5 h-1.5 rounded-full ${f.dot}`} />} label={f.label}
                  count={assets.filter(f.match).length}
                  active={consistencyFilter === f.id} onClick={() => setConsistencyFilter(consistencyFilter === f.id ? null : f.id)} />
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-violet-900/50 bg-violet-950/30 p-2.5 text-[10px] text-violet-200/80">
            Locked assets carry their LoRA, trigger word and seed into every LTX / Wan shot that references them.
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {visible.length === 0 && (
            <p className="text-xs text-zinc-600 mb-4">
              {assets.length === 0 ? 'No assets yet — build one from a single image, or create one manually.' : 'Nothing matches this filter.'}
            </p>
          )}
          <div className="grid grid-cols-3 xl:grid-cols-4 gap-4">
            {visible.map(asset => (
              <AssetCard key={asset.id} asset={asset} selected={false} onSelect={() => onSelect(asset.id)} onRemove={() => onRemove(asset)} />
            ))}
            <button onClick={onOpenWizard} data-testid="new-asset-ghost"
              className="rounded-xl border-2 border-dashed border-zinc-800 hover:border-violet-700 text-zinc-600 hover:text-violet-300 flex flex-col items-center justify-center gap-2 aspect-[4/3] transition-colors">
              <Plus className="h-6 w-6" />
              <span className="text-xs">New asset</span>
              <span className="text-[10px] text-zinc-700">one image → full kit</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function RailRow({ icon, label, count, active, onClick }: {
  icon?: React.ReactNode; label: string; count: number; active: boolean; onClick: () => void
}) {
  return (
    <button onClick={onClick}
      className={'w-full flex items-center gap-2 px-2 py-1 rounded text-left text-[11px] transition-colors ' + (active ? 'bg-violet-900/40 text-violet-200' : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200')}>
      {icon && <span className="flex items-center [&>svg]:h-3.5 [&>svg]:w-3.5">{icon}</span>}
      <span className="flex-1 truncate">{label}</span>
      <span className="text-[10px] text-zinc-600">{count}</span>
    </button>
  )
}
