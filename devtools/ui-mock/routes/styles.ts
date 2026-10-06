/**
 * The style library, simulated: styles saved in memory, their picture a placeholder.
 * The real one reads the style with a vision model (backend handlers/style_library_handler.py).
 */

import { MockHttpError, type Router } from '../http'
import { placeholderFrame } from '../media'

interface MockStyle {
  id: string
  name: string
  style_prompt: string
  style_guide: null
  images: string[]
  created_at: number
}

export function registerStyleRoutes(router: Router): void {
  const styles: MockStyle[] = []

  router.get('/api/styles', () => ({ styles: [...styles].sort((a, b) => b.created_at - a.created_at) }))

  router.post('/api/styles', (req) => {
    const name = String(req.body.name ?? '').trim()
    const images = Array.isArray(req.body.images_base64) ? req.body.images_base64 : []
    if (!name) throw new MockHttpError(400, 'Name the style')
    if (images.length === 0) throw new MockHttpError(400, 'Add at least one picture of the style')
    const id = `style-${styles.length + 1}-${Date.now()}`
    const style: MockStyle = {
      id, name, style_prompt: `${name} (UI mock: no vision model read it)`, style_guide: null,
      images: images.slice(0, 6).map((_, i) => `${id}-${i}.png`), created_at: Date.now(),
    }
    styles.push(style)
    return style
  })

  router.delete('/api/styles/:id', (req) => {
    const index = styles.findIndex(s => s.id === req.params.id)
    if (index < 0) throw new MockHttpError(404, `Style not found: ${req.params.id}`)
    styles.splice(index, 1)
    return { status: 'ok' }
  })

  router.get('/api/styles/:id/images/:index', (req) => {
    const style = styles.find(s => s.id === req.params.id)
    if (!style) throw new MockHttpError(404, 'No such style picture')
    return placeholderFrame(style.name, 'style picture')
  })
}
