// @vitest-environment jsdom
/**
 * The settings sync contract that Model Library's "Use" button depends on.
 *
 * updateSettings() only sets React state; the POST behind it is debounced by
 * 150ms. Calling refreshSettings() straight afterwards therefore GETs the
 * server's pre-change values and puts them back over the patch, after which
 * the debounce re-POSTs the stale ones - so the patch is silently lost.
 *
 * These render the real AppSettingsProvider against an in-memory backend, so
 * the payload asserted here is the one that would go over the wire.
 */
import { createElement, type ReactNode } from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { AppSettingsProvider, useAppSettings } from './AppSettingsContext'
import { resetBackendCredentials } from '../lib/backend'

const DEBOUNCE_MS = 150

interface FakeBackend {
  stored: Record<string, unknown>
  posts: Record<string, unknown>[]
}

let backend: FakeBackend

function installBackend(): void {
  backend = { stored: { mediaProvider: 'local', defaultVideoModel: '', defaultImageModel: '' }, posts: [] }

  // Environment stubs only - the code under test is the real provider.
  ;(window as unknown as { electronAPI: unknown }).electronAPI = {
    getBackend: async () => ({ url: 'http://127.0.0.1:8000', token: '' }),
    getBackendHealthStatus: async () => ({ status: 'alive' }),
    onBackendHealthStatus: (_handler: (value: unknown) => void) => () => {},
  }

  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const ok = (body: unknown) =>
      ({ ok: true, status: 200, json: async () => body }) as unknown as Response

    if (url.endsWith('/api/runtime-policy')) return ok({})
    if (url.endsWith('/api/settings') && method === 'GET') return ok({ ...backend.stored })
    if (url.endsWith('/api/settings') && method === 'POST') {
      const payload = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
      backend.posts.push(payload)
      backend.stored = { ...backend.stored, ...payload }
      return ok({ ...backend.stored })
    }
    return ok({})
  }) as typeof fetch
}

/** The live context value, captured from inside the provider. */
function harness(): { current: ReturnType<typeof useAppSettings> | null } {
  const ref: { current: ReturnType<typeof useAppSettings> | null } = { current: null }
  function Probe(): ReactNode {
    ref.current = useAppSettings()
    return null
  }
  render(createElement(AppSettingsProvider, null, createElement(Probe)))
  return ref
}

const settle = (ms: number) => act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) })

describe('app settings sync', () => {
  beforeEach(() => {
    installBackend()
    resetBackendCredentials()
  })

  afterEach(() => {
    cleanup()
    resetBackendCredentials()
  })

  it('posts a patch made through updateSettings', async () => {
    const context = harness()
    await settle(50)
    expect(context.current?.isLoaded).toBe(true)

    act(() => {
      context.current?.updateSettings({ mediaProvider: 'fal', defaultVideoModel: 'fal-ai/ltx-video' })
    })
    await settle(DEBOUNCE_MS + 100)

    const last = backend.posts.at(-1)
    expect(last?.mediaProvider).toBe('fal')
    expect(last?.defaultVideoModel).toBe('fal-ai/ltx-video')
    expect(backend.stored.defaultVideoModel).toBe('fal-ai/ltx-video')
  })

  it('loses the patch when refreshSettings runs before the debounce fires', async () => {
    // This is the bug Model Library's "Use" button had: it is a property of
    // the context, so the only fix is not to call refreshSettings there.
    const context = harness()
    await settle(50)

    await act(async () => {
      context.current?.updateSettings({ mediaProvider: 'fal', defaultVideoModel: 'fal-ai/ltx-video' })
      await context.current?.refreshSettings()
    })
    await settle(DEBOUNCE_MS + 100)

    expect(backend.stored.defaultVideoModel).toBe('')
    expect(backend.stored.mediaProvider).toBe('local')
  })
})

describe('Model Library persistence', () => {
  it('never re-reads settings after patching them', () => {
    const source = readFileSync(resolve(process.cwd(), 'frontend/views/film/ModelLibrary.tsx'), 'utf8')
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
    // Guards the fix above: re-reading settings anywhere in this view races
    // the debounced write and silently drops whatever "Use" just set.
    expect(code).not.toMatch(/refreshSettings\s*\(/)
  })
})
