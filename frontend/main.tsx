import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { installBrowserElectronShim } from './lib/browser-electron-shim'
import './index.css'

// No-op under Electron; enables plain-browser development against :8000.
installBrowserElectronShim()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
