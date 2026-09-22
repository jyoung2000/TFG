import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import renderer from 'vite-plugin-electron-renderer'
import net from 'net'
import path from 'path'
import { isUiMockEnabled, isUiStandalone, uiMockPlugin } from './devtools/ui-mock/node-adapter'
import { singleFilePlugin } from './devtools/ui-mock/single-file'

// Find a free TCP port at or above `start`. Electron hard-crashes when
// --inspect/--remote-debugging-port points at a port another process holds
// (e.g. a stale Electron from a previous dev session), so dev launches probe
// for a free port instead of hardcoding one.
async function resolveFreePort(start: number): Promise<number> {
  for (let port = start; port < start + 100; port++) {
    const free = await new Promise<boolean>(resolve => {
      const server = net.createServer()
      server.once('error', () => resolve(false))
      server.once('listening', () => server.close(() => resolve(true)))
      server.listen(port, '127.0.0.1')
    })
    if (free) {
      return port
    }
  }
  throw new Error(`No free port found at or above ${start}`)
}

// UI-only mode (`pnpm dev:ui`): the renderer runs in a plain browser against a
// mock backend, so no Python, Electron, GPU or model weights are needed to work
// on the interface. Everything Electron-specific is skipped.
//
// Standalone (`pnpm build:ui`) goes further: the mock runs in the browser and
// the whole app is folded into one HTML file that opens from disk.
const standalone = isUiStandalone()
const uiOnly = isUiMockEnabled() || standalone

export default defineConfig({
  plugins: [
    react(),
    ...(uiOnly && !standalone ? [uiMockPlugin(path.resolve(__dirname, 'node_modules/.cache/ui-mock/state.json'))] : []),
    ...(standalone ? [singleFilePlugin()] : []),
    ...(uiOnly ? [] : electron([
      {
        entry: 'electron/main.ts',
        onstart(options) {
          if (process.env.ELECTRON_DEBUG) {
            // --inspect and --remote-debugging-port must come before '.' (the app path)
            // A fixed --inspect port hard-crashes Electron when it is already
            // bound (bind error 0x2740 -> devtools http server fails to start),
            // so resolve a free port at launch unless one is pinned.
            void (async () => {
              const inspectorPort = await resolveFreePort(
                Number(process.env.ELECTRON_INSPECT_PORT) || 9229
              )
              const chromePort = await resolveFreePort(
                Number(process.env.ELECTRON_REMOTE_DEBUG_PORT) || 9222
              )
              options.startup([
                `--inspect=${inspectorPort}`,
                `--remote-debugging-port=${chromePort}`,
                '.',
                '--no-sandbox',
              ])
            })()
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
  // The standalone page is meant to be one file you can pass around, so the
  // public/ folder (a 27 MB decorative hero video among it) is not copied.
  publicDir: standalone ? false : undefined,
  build: standalone
    ? {
        // Written into the repo so the file can be downloaded and opened
        // without building anything; emptyOutDir would wipe the README.
        outDir: 'ui-preview',
        emptyOutDir: false,
        // A `file://` page cannot load ES modules, so the whole app has to be
        // one classic script: no code splitting, no module preloads.
        modulePreload: false,
        cssCodeSplit: false,
        assetsInlineLimit: Number.MAX_SAFE_INTEGER,
        rollupOptions: {
          output: {
            format: 'iife',
            inlineDynamicImports: true,
          },
        },
      }
    : {
        outDir: 'dist'
      }
})
