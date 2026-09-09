import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { installBrowserElectronShim } from './lib/browser-electron-shim'
import { seedDemoProject } from './lib/ui-mock-projects'
import './index.css'

// No-op under Electron; enables plain-browser development against :8000.
installBrowserElectronShim()

// UI-only mode (`pnpm dev:ui`): put the demo film on Home before the first
// render, since the project list is read from localStorage synchronously.
// Vite replaces the flag with a literal, so this and the module it imports are
// eliminated from production builds.
if (import.meta.env.VITE_UI_MOCK === '1') {
  seedDemoProject()
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
