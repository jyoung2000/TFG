/**
 * The app-wide style library (backend handlers/style_library_handler.py): art styles
 * saved from pictures, reverse-engineered by the vision AI, used by the image and
 * video generators through `styleId`.
 */
import { backendFetch } from './backend'

export interface SavedStyle {
  id: string
  name: string
  style_prompt: string
  style_guide: { key_traits: string[]; color_palette: string[]; mood: string; recommended_prompt: string } | null
  images: string[]
  created_at: number
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { error?: string; detail?: string }
    throw new Error(body.error || body.detail || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const stylesApi = {
  list: async (): Promise<SavedStyle[]> => (await json<{ styles: SavedStyle[] }>(await backendFetch('/api/styles'))).styles,

  /** Save a style from its pictures (data URLs); the vision AI reads up to three. */
  create: async (name: string, imagesBase64: string[]): Promise<SavedStyle> =>
    json<SavedStyle>(await backendFetch('/api/styles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, images_base64: imagesBase64 }),
    })),

  remove: async (id: string): Promise<void> => {
    await json(await backendFetch(`/api/styles/${encodeURIComponent(id)}`, { method: 'DELETE' }))
  },

  /** An object URL of one of the style's pictures (fetched with the backend's auth). */
  imageUrl: async (id: string, index = 0): Promise<string> => {
    const response = await backendFetch(`/api/styles/${encodeURIComponent(id)}/images/${index}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return URL.createObjectURL(await response.blob())
  },
}
