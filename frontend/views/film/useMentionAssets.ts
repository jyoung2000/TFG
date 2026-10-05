/** Film assets as @-mention options, with thumbnail URLs resolved like the asset cards do. */

import { useEffect, useMemo, useState } from 'react'
import type { MentionAsset } from '../../components/ui/AssetMentionTextarea'
import { useFilm } from '../../contexts/FilmContext'
import { filmMediaUrl } from '../../lib/film-api'

export function useMentionAssets(): MentionAsset[] {
  const { film } = useFilm()
  const filmId = film?.id
  const assets = film?.assets
  const [urls, setUrls] = useState<Record<string, string>>({})
  const key = (assets ?? []).map(a => `${a.id}:${a.reference_images[0] ?? ''}`).join('|')
  useEffect(() => {
    let cancelled = false
    if (!filmId || !assets) return
    void Promise.all(assets.map(async (a): Promise<[string, string] | null> => {
      const path = a.reference_images[0]
      if (!path) return null
      try { return [a.id, await filmMediaUrl(filmId, path)] } catch { return null }
    })).then(pairs => {
      if (!cancelled) setUrls(Object.fromEntries(pairs.filter((p): p is [string, string] => p !== null)))
    })
    return () => { cancelled = true }
    // key stands for the assets' reference paths
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filmId, key])
  return useMemo(
    () => (assets ?? []).map(a => ({ id: a.id, name: a.name, kind: a.kind, thumbnailUrl: urls[a.id] })),
    [assets, urls],
  )
}
