/**
 * Deliver: deterministic passes from the composer scene.
 *
 * Adapted from Blockout's Deliver pipeline (`src/renderer/export/exporter.ts`,
 * wassermanproductions/blockout, Apache-2.0 — NOTICE in this folder): the
 * timeline is stepped at exactly the shot's fps, every frame is rendered from
 * the same keyframe state the preview uses, and clean / depth / normal passes
 * plus stills go out as PNG. Encoding happens in the backend (ffmpeg through
 * `services/stitcher`), not in a renderer-side ffmpeg, and the package lands
 * in the film project as the shot's control signals.
 */

import * as THREE from 'three'

export type DeliverPass = 'clean' | 'depth' | 'normal'

export interface DeliverFrames {
  fps: number
  width: number
  height: number
  clean: string[]
  depth: string[]
  normal: string[]
  stills: string[]
}

export interface DeliverRenderer {
  /** Put the scene at time t (camera + keyframed objects). */
  seek(time: number): void
  /** Render the shot camera at the given size with a pass override; returns base64 PNG (no data: prefix). */
  renderPass(pass: DeliverPass, width: number, height: number): string
}

export interface DeliverOptions {
  durationSeconds: number
  fps: number
  width: number
  height: number
  passes: Record<DeliverPass, boolean>
  /** Times (seconds) for stills; defaults to first + last frame. */
  stillTimes?: number[]
  onProgress?: (done: number, total: number) => void
  isCancelled?: () => boolean
}

/** Materials that turn the scene into a depth or normal pass without touching object materials. */
export function passOverride(pass: DeliverPass, near: number, far: number): THREE.Material | null {
  if (pass === 'depth') {
    const material = new THREE.MeshDepthMaterial({ depthPacking: THREE.BasicDepthPacking })
    // Normalised across the whole shot so the gradient does not pump as subjects approach.
    material.userData = { near, far }
    return material
  }
  if (pass === 'normal') return new THREE.MeshNormalMaterial()
  return null
}

/** Even dimensions keep H.264 encoders happy. */
export function evenDims(width: number, height: number): { width: number; height: number } {
  const even = (n: number) => (Math.round(n) % 2 === 0 ? Math.round(n) : Math.round(n) + 1)
  return { width: even(width), height: even(height) }
}

export async function renderDeliver(renderer: DeliverRenderer, options: DeliverOptions): Promise<DeliverFrames> {
  const { width, height } = evenDims(options.width, options.height)
  const fps = Math.max(1, Math.min(60, Math.round(options.fps)))
  const totalFrames = Math.max(1, Math.round(options.durationSeconds * fps))
  const passes = (['clean', 'depth', 'normal'] as DeliverPass[]).filter(p => options.passes[p])
  const out: DeliverFrames = { fps, width, height, clean: [], depth: [], normal: [], stills: [] }
  const total = totalFrames * passes.length
  let done = 0
  for (const pass of passes) {
    for (let i = 0; i < totalFrames; i++) {
      if (options.isCancelled?.()) return out
      renderer.seek(i / fps)
      out[pass].push(renderer.renderPass(pass, width, height))
      done += 1
      options.onProgress?.(done, total)
      if (i % 6 === 5) await new Promise(resolve => setTimeout(resolve, 0))
    }
  }
  const stillTimes = options.stillTimes ?? [0, Math.max(0, options.durationSeconds - 1 / fps)]
  for (const t of stillTimes) {
    renderer.seek(t)
    out.stills.push(renderer.renderPass('clean', width, height))
  }
  renderer.seek(0)
  return out
}
