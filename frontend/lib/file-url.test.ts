import { describe, expect, it } from 'vitest'
import { toFileUrl } from './file-url'

// These run without VITE_UI_MOCK, so they pin the packaged app's behaviour:
// the URL Electron's renderer is allowed to load.
describe('toFileUrl', () => {
  it('keeps a POSIX absolute path at two slashes', () => {
    expect(toFileUrl('/home/you/outputs/clip.mp4')).toBe('file:///home/you/outputs/clip.mp4')
  })

  it('normalises Windows separators and adds the third slash', () => {
    expect(toFileUrl('C:\\Users\\you\\outputs\\clip.mp4')).toBe('file:///C:/Users/you/outputs/clip.mp4')
  })

  it('normalises before deciding, so a UNC-style path is not mistaken for relative', () => {
    expect(toFileUrl('\\\\server\\share\\clip.mp4')).toBe('file:////server/share/clip.mp4')
  })

  it('treats a relative path as relative', () => {
    expect(toFileUrl('outputs/clip.mp4')).toBe('file:///outputs/clip.mp4')
  })

  it('percent-encodes characters that break a file URL', () => {
    expect(toFileUrl('C:\\My Videos\\#1 take 100%.mp4')).toBe('file:///C:/My%20Videos/%231%20take%20100%25.mp4')
  })

  it('leaves an already-safe path untouched', () => {
    expect(toFileUrl('/srv/out/clip_01.mp4')).toBe('file:///srv/out/clip_01.mp4')
  })
})
