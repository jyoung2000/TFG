import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import renderer from 'vite-plugin-electron-renderer'
import path from 'path'
import { isUiMockEnabled, uiMockPlugin } from './devtools/ui-mock/plugin'

// UI-only mode (`pnpm dev:ui`): the renderer runs in a plain browser against a
// mock backend, so no Python, Electron, GPU or model weights are needed to work
// on the interface. Everything Electron-specific is skipped.
const uiOnly = isUiMockEnabled()

export default defineConfig({
  plugins: [
    react(),
    ...(uiOnly ? [uiMockPlugin(path.resolve(__dirname, 'node_modules/.cache/ui-mock/state.json'))] : []),
    ...(uiOnly ? [] : electron([
      {
        entry: 'electron/main.ts',
        onstart(options) {
          if (process.env.ELECTRON_DEBUG) {
            // --inspect and --remote-debugging-port must come before '.' (the app path)
            options.startup(['--inspect=9229', '--remote-debugging-port=9222', '.', '--no-sandbox'])
          } else {
            options.startup()
          }
        },
        vite: {
          build: {
            outDir: 'dist-electron',
            sourcemap: true,
            rollupOptions: {
              external: ['electron']
            }
          }
        }
      },
      {
        entry: 'electron/preload.ts',
        onstart(options) {
          options.reload()
        },
        vite: {
          build: {
            outDir: 'dist-electron',
            sourcemap: true,
            rollupOptions: {
              output: {
                format: 'cjs'  // Preload must be CommonJS
              }
            }
          }
        }
      }
    ])),
    ...(uiOnly ? [] : [renderer()])
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './frontend')
    }
  },
  base: './',  // Use relative paths for Electron file:// protocol
  build: {
    outDir: 'dist'
  }
})
