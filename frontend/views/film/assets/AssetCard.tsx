/** One asset in the library grid: thumb, status badge, consistency pips. */

import { Lock, Trash2 } from 'lucide-react'
import type { FilmAsset } from '../../../types/film'
import { assetStatus, consistencyOf, sheetImages, type AssetStatus } from './consistency'
import { KIND_META, ThumbError, paletteSwatch, useFilmMediaUrl } from './shared'

const STATUS_META: Record<Exclude<AssetStatus, 'empty'>, { label: string; className: string; lock?: boolean }> = {
  locked: { label: 'Locked', className: 'bg-emerald-900/60 text-emerald-300', lock: true },
  'needs-lora': { label: 'Needs LoRA', className: 'bg-amber-900/50 text-amber-300' },
  'no-seed': { label: 'No seed lock', className: 'bg-red-950/50 text-red-300' },
  drift: { label: 'Drift risk', className: 'bg-red-950/50 text-red-300' },
  style: { label: 'Every shot', className: 'bg-violet-900/60 text-violet-300' },
}

export function ConsistencyPips({ asset, size = 'text-[8px]' }: { asset: FilmAsset; size?: string }) {
  const c = consistencyOf(asset)
  const pips = asset.kind === 'style'
    ? ([['REF', c.ref], ['GUIDE', c.guide]] as const)
    : ([['REF', c.ref], ['GUIDE', c.guide], ['LORA', c.lora], ['SEED', c.seed]] as const)
  return (
    <div className="flex gap-1" aria-label={`Consistency ${c.count} of ${asset.kind === 'style' ? 2 : 4}`}>
      {pips.map(([label, on]) => (
        <span key={label} className={`flex-1 text-center rounded py-0.5 font-bold tracking-widest ${size} ${on ? 'bg-emerald-500/15 text-emerald-400' : 'bg-zinc-800 text-zinc-600'}`}>
          {label}
        </span>
      ))}
    </div>
  )
}

export function AssetCard({ asset, selected, onSelect, onRemove }: {
  asset: FilmAsset; selected: boolean; onSelect: () => void; onRemove: () => void
}) {
  const thumb = useFilmMediaUrl(asset.reference_images[0])
  const meta = KIND_META[asset.kind]
  const status = assetStatus(asset)
  const badge = status === 'empty' ? null : STATUS_META[status]
  const hasSheet = sheetImages(asset).every(s => s.path !== null)
  return (
    <div onClick={onSelect} data-testid="asset-card"
      className={'group relative rounded-xl overflow-hidden border cursor-pointer transition-all ' + (selected ? 'border-violet-500 ring-2 ring-violet-500/30' : 'border-zinc-800 hover:border-zinc-600')}
      title={asset.name}>
      <div className="aspect-[4/3] bg-zinc-950 relative">
        {thumb.status === 'ready'
          ? <img src={thumb.url} alt="" loading="lazy" className="w-full h-full object-cover" />
          : thumb.status === 'error' && asset.reference_images.length > 0
            ? <ThumbError className="w-full h-full" message={thumb.message} />
            : (
              <div className={`w-full h-full bg-gradient-to-br ${meta.gradient} flex items-center justify-center`}>
                <span className="text-zinc-600 opacity-40 [&>svg]:h-12 [&>svg]:w-12">{meta.icon}</span>
              </div>
            )}
        <span className={'absolute top-2 left-2 px-1.5 py-0.5 rounded text-[10px] font-medium ' + meta.color}>{meta.label}</span>
        {badge && (
          <span className={'absolute top-2 right-2 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ' + badge.className}>
            {badge.lock && <Lock className="h-2.5 w-2.5" />}{badge.label}
          </span>
        )}
        {asset.reference_images.length > 0 && (
          <span className="absolute bottom-2 left-2 px-1.5 py-0.5 rounded bg-zinc-950/80 text-[10px] text-zinc-300">
            {asset.reference_images.length} ref{asset.reference_images.length === 1 ? '' : 's'}{hasSheet ? ' · sheet ✓' : ''}
          </span>
        )}
        <button onClick={e => { e.stopPropagation(); onRemove() }}
          className="absolute top-8 right-2 p-1.5 rounded-lg bg-zinc-950/70 text-zinc-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
          aria-label={'Delete ' + asset.name}><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      <div className="px-3 py-2 bg-zinc-900/95 space-y-1.5">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-xs font-semibold text-zinc-100 truncate">{asset.name}</span>
          {asset.seed_lock !== null && <span className="ml-auto shrink-0 text-[10px] text-zinc-500 font-mono">seed {asset.seed_lock}</span>}
        </div>
        <ConsistencyPips asset={asset} />
        <div className="flex items-center gap-1 min-w-0 h-3">
          {(asset.style_guide?.color_palette ?? []).slice(0, 4).map((c, i) => (
            <span key={i} className="w-4 h-2 rounded-sm border border-zinc-800 shrink-0" title={c} style={{ background: paletteSwatch(c) }} />
          ))}
          {asset.lora_id !== '' && (
            <span className="text-[9px] text-zinc-500 truncate">{asset.lora_trigger || 'lora'} @ {asset.lora_multiplier}</span>
          )}
        </div>
      </div>
    </div>
  )
}
