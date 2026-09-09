/**
 * Folds the built app into one HTML file that opens by double-clicking.
 *
 * A `file://` page cannot load ES modules or fetch anything, so the normal
 * Vite output — `index.html` plus module scripts and a stylesheet — will not
 * run from disk. This inlines the CSS and the (IIFE) bundle into the HTML and
 * drops the module preloads, leaving a page with no external requests at all.
 */

import type { Plugin } from 'vite'

const OUTPUT_NAME = 'ltx-desktop-ui.html'

/** Inline content can contain `</script>`, which would end the tag early. */
function escapeForScript(code: string): string {
  return code.replace(/<\/script>/gi, '<\\/script>')
}

export function singleFilePlugin(): Plugin {
  return {
    name: 'ltx-ui-single-file',
    apply: 'build',
    enforce: 'post',
    generateBundle(_options, bundle) {
      const htmlKey = Object.keys(bundle).find(name => name.endsWith('.html'))
      if (!htmlKey) return
      const htmlAsset = bundle[htmlKey]
      if (htmlAsset.type !== 'asset' || typeof htmlAsset.source !== 'string') return

      let html = htmlAsset.source
      const consumed: string[] = []

      let entryCode = ''
      for (const [name, chunk] of Object.entries(bundle)) {
        // Replacement *functions* throughout: bundled code is full of `$&` and
        // `$'`, which the string form of replace would expand as patterns.
        if (chunk.type === 'chunk' && chunk.isEntry) {
          entryCode = chunk.code
          html = html.replace(
            new RegExp(`<script[^>]*src="[^"]*${escapeRegex(name)}"[^>]*></script>`),
            () => '',
          )
          consumed.push(name)
        } else if (chunk.type === 'asset' && name.endsWith('.css') && typeof chunk.source === 'string') {
          const style = `<style>${chunk.source}</style>`
          html = html.replace(new RegExp(`<link[^>]*href="[^"]*${escapeRegex(name)}"[^>]*>`), () => style)
          consumed.push(name)
        }
      }

      // Preload hints point at files that no longer exist beside the page.
      html = html.replace(/<link[^>]*rel="modulepreload"[^>]*>/g, '')

      // Vite hoists the entry into <head>, which is fine for a deferred module
      // script but not for an inline classic one: it would run before #root
      // exists. Put it last in <body> instead.
      if (entryCode) {
        const tag = `<script>${escapeForScript(entryCode)}</script>`
        html = html.includes('</body>')
          ? html.replace('</body>', () => `${tag}</body>`)
          : html + tag
      }

      for (const name of consumed) delete bundle[name]
      delete bundle[htmlKey]

      this.emitFile({ type: 'asset', fileName: OUTPUT_NAME, source: html })
    },
  }
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
