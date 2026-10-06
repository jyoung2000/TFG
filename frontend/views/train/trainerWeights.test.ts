import { describe, expect, it } from 'vitest'
import { trainerChip, weightStatus } from './trainerWeights'

/* QA pass 2026-10-01 (LoRA trainer). Nothing in the app set the trainer's
 * model files: Start was enabled and a musubi run failed minutes in with
 * "Weights missing ... Set them in Train -> Trainer settings" - a panel that
 * did not exist. The Train screen now shows each file the target needs and
 * whether it is there, and Start waits until they are. */

describe('weightStatus', () => {
  it('a musubi target with nothing set needs all three files', () => {
    const status = weightStatus({ z_image: { dit: '', vae: '', text_encoder: '' } }, 'z_image')
    expect(status.ready).toBe(false)
    expect(status.rows.map(r => [r.key, r.state])).toEqual([['dit', 'unset'], ['vae', 'unset'], ['text_encoder', 'unset']])
    expect(status.blocker).toBe('Set the model files for this target (Trainer settings): DiT model, VAE, Text encoder.')
  })

  it('a file that has gone from disk is shown as missing, with its path', () => {
    const status = weightStatus({ z_image: { dit: 'C:/m/dit.safetensors', vae: 'missing: C:/m/vae.safetensors', text_encoder: 'C:/m/te.safetensors' } }, 'z_image')
    expect(status.ready).toBe(false)
    expect(status.rows[1]).toEqual({ key: 'vae', label: 'VAE', state: 'missing', path: 'C:/m/vae.safetensors' })
  })

  it('all files present: ready', () => {
    const status = weightStatus({ qwen_image: { dit: 'a', vae: 'b', text_encoder: 'c' } }, 'qwen_image')
    expect(status.ready).toBe(true)
    expect(status.blocker).toBe('')
  })

  it('a target that loads by model name (FLUX via ai-toolkit) needs no file', () => {
    expect(weightStatus({ flux: { name_or_path: '' } }, 'flux').ready).toBe(true)
    expect(weightStatus({}, 'flux').ready).toBe(true)
  })
})

describe('trainerChip', () => {
  const musubi = { installed: true, fits_12gb: true, reason: '', notes: '', targets: ['wan', 'ltx'] }
  it('is not "ready" while no target has its model files', () => {
    const chip = trainerChip(musubi, { wan: { dit: '', vae: '' }, ltx: { dit: 'missing: D:/x.safetensors' } })
    expect(chip.text).toBe('needs model files')
    expect(chip.tone).toBe('warn')
  })
  it('is ready once one target has every file, or needs none', () => {
    expect(trainerChip(musubi, { wan: { dit: 'D:/dit.safetensors', vae: 'D:/vae.safetensors' }, ltx: { dit: '' } }).text).toBe('ready')
    expect(trainerChip({ ...musubi, targets: ['flux'] }, {}).text).toBe('ready')
  })
  it('believes the backend about which targets can start', () => {
    // QA 2026-10-02 (r50): FLUX's name-only row made musubi look ready with no files set.
    expect(trainerChip({ ...musubi, ready_targets: [] }, { wan: { dit: '' }, ltx: { name_or_path: '' } }).text).toBe('needs model files')
    expect(trainerChip({ ...musubi, ready_targets: ['z_image'] }, {}).title).toContain('z_image')
  })
  it('says why a trainer is unavailable', () => {
    expect(trainerChip({ ...musubi, installed: false }, {}).text).toBe('not installed')
    expect(trainerChip({ ...musubi, installed: false, fits_12gb: false }, {}).text).toBe('needs more than 12 GB')
  })
})
