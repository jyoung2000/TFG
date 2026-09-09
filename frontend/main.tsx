import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { installBrowserElectronShim } from './lib/browser-electron-shim'
import { seedDemoProject } from './lib/ui-mock-projects'
import { setMediaResolver } from './lib/media-resolver'
import { installBrowserMock } from '../devtools/ui-mock/browser'
import './index.css'

// No-op under Electron; enables plain-browser development against :8000.
installBrowserElectronShim()

// The standalone build (`pnpm build:ui`) has no server: run the same mock
// backend in this tab and answer media from data/blob URLs. Must happen before
// anything fetches.
if (import.meta.env.VITE_UI_STANDALONE === '1') {
  setMediaResolver(installBrowserMock().media)
}

// UI-only modes put the demo film on Home before the first render, since the
// project list is read from localStorage synchronously. Vite replaces the flags
// with literals, so all of this is eliminated from the app build.
if (import.meta.env.VITE_UI_MOCK === '1' || import.meta.env.VITE_UI_STANDALONE === '1') {
  seedDemoProject()
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
