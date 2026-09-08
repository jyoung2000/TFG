import { describe, expect, it } from 'vitest'
import { conversionSourceFromAsset } from './film-conversion'
import type { Asset } from '../types/project'

const asset: Asset = {
  id: 'a1',
  type: 'video',
  path: '/tmp/clip.mp4',
  url: 'file:///tmp/clip.mp4',
  prompt: 'fallback prompt',
  resolution: '720p',
  duration: 6,
  createdAt: 1,
}

describe('conversionSourceFromAsset', () => {
  it('prefers the generation record over asset fields', () => {
    const source = conversionSourceFromAsset({
      ...asset,
      generationParams: {
        mode: 'image-to-video',
        prompt: 'generated prompt',
        model: 'pro',
        duration: 8,
        resolution: '1080p',
        fps: 25,
        audio: false,
        cameraMotion: 'dolly_in',
        imageAspectRatio: '9:16',
        inputImageUrl: 'file:///refs/frame.png',
      },
    })
    expect(source).toMatchObject({
      outputPath: '/tmp/clip.mp4',
      prompt: 'generated prompt',
      model: 'pro',
      resolution: '1080p',
      durationSeconds: 8,
      fps: 25,
      aspectRatio: '9:16',
      cameraMotion: 'dolly_in',
      mode: 'image-to-video',
      inputImagePath: '/refs/frame.png',
    })
  })

  it('falls back to the asset when there is no generation record', () => {
    const source = conversionSourceFromAsset(asset)
    expect(source.prompt).toBe('fallback prompt')
    expect(source.resolution).toBe('720p')
    expect(source.durationSeconds).toBe(6)
    expect(source.model).toBeUndefined()
    expect(source.inputImagePath).toBeUndefined()
  })

  it('never produces an empty prompt', () => {
    expect(conversionSourceFromAsset({ ...asset, prompt: '' }).prompt).toBe('Imported clip')
  })
})
