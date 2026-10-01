/**
 * The Assets tab: a visual-first library of characters, locations, props
 * and styles built around the consistency contract (REF/GUIDE/LORA/SEED —
 * see `assets/consistency.ts`). This file is only the view router; the
 * three layouts live under `assets/`:
 *
 *   grid   — the full-width library (`assets/AssetGrid.tsx`)
 *   detail — one asset (`assets/AssetDetail.tsx`)
 *   wizard — one seed image → AI-built kit (`assets/NewAssetWizard.tsx`)
 */

import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { Lightbox } from '../../components/Lightbox'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi } from '../../lib/film-api'
import type { FilmAsset, FilmAssetKind } from '../../types/film'
import { AssetDetail } from './assets/AssetDetail'
import { AssetGrid } from './assets/AssetGrid'
import { NewAssetWizard } from './assets/NewAssetWizard'
import { KIND_META, useReferenceUrls } from './assets/shared'
import { studioScene, studioShot } from './assets/studio'

const ShotComposer = lazy(() => import('./composer/ShotComposer'))

type View = { kind: 'grid' } | { kind: 'detail'; id: string } | { kind: 'wizard' }

export function AssetsPanel() {
  const { film, refresh } = useFilm()
  const [view, setView] = useState<View>({ kind: 'grid' })
  const selected = view.kind === 'detail' ? (film?.assets.find(a => a.id === view.id) ?? null) : null
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)
  // The 3D composer on one asset (pose, camera, multi-angle LoRA shots).
  const [studioId, setStudioId] = useState<string | null>(null)
  const studioAsset = studioId ? (film?.assets.find(a => a.id === studioId) ?? null) : null
  const lightboxItems = useReferenceUrls(selected)
  useEffect(() => { setLightboxIndex(null) }, [selected?.id])

  const create = useCallback(async (kind: FilmAssetKind) => {
    if (!film) return
    const count = film.assets.filter(a => a.kind === kind).length
    const asset = await filmApi.createAsset(film.id, { kind, name: KIND_META[kind].label + ' ' + (count + 1) })
    await refresh()
    setView({ kind: 'detail', id: asset.id })
  }, [film, refresh])

  const remove = useCallback(async (asset: FilmAsset) => {
    if (!film || !window.confirm('Delete ' + asset.name + '?')) return
    await filmApi.deleteAsset(film.id, asset.id)
    setView(current => (current.kind === 'detail' && current.id === asset.id ? { kind: 'grid' } : current))
    await refresh()
  }, [film, refresh])

  if (!film) return null

  return (
    <div className="h-full min-h-0 relative">
      {view.kind === 'grid' && (
        <AssetGrid assets={film.assets}
          onSelect={id => setView({ kind: 'detail', id })}
          onRemove={asset => void remove(asset)}
          onCreate={kind => void create(kind)}
          onOpenWizard={() => setView({ kind: 'wizard' })} />
      )}
      {view.kind === 'detail' && selected && (
        <AssetDetail asset={selected} onBack={() => setView({ kind: 'grid' })} onOpenLightbox={setLightboxIndex} onOpenStudio={() => setStudioId(selected.id)} />
      )}
      {view.kind === 'detail' && !selected && (
        // The asset vanished under us (deleted elsewhere) — fall back home.
        <AssetGrid assets={film.assets}
          onSelect={id => setView({ kind: 'detail', id })}
          onRemove={asset => void remove(asset)}
          onCreate={kind => void create(kind)}
          onOpenWizard={() => setView({ kind: 'wizard' })} />
      )}
      {view.kind === 'wizard' && (
        <NewAssetWizard onClose={() => setView({ kind: 'grid' })} onDone={id => setView({ kind: 'detail', id })} />
      )}
      {studioAsset && (
        <Suspense fallback={null}>
          <ShotComposer
            projectId={film.id}
            scene={studioScene(studioAsset)}
            shot={studioShot(studioAsset, film)}
            onClose={() => { setStudioId(null); void refresh() }}
            studio={{
              title: studioAsset.name,
              onSave: async composition => { await filmApi.updateAsset(film.id, studioAsset.id, { composition }) },
            }}
          />
        </Suspense>
      )}
      {lightboxIndex !== null && lightboxItems.length > 0 && (
        <Lightbox
          items={lightboxItems}
          index={Math.min(lightboxIndex, lightboxItems.length - 1)}
          onClose={() => setLightboxIndex(null)}
          onIndexChange={setLightboxIndex}
        />
      )}
    </div>
  )
}
