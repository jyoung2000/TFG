/**
 * The run's VRAM estimate as Block swap changes (QA pass 2026-10-02): the
 * Train screen showed a fixed number, so raising Block swap looked useless.
 * Mirrors backend `film/training_presets.estimate_vram_mb` - keep in sync:
 * the backend's figure is the one the run is held to.
 */

import type { TrainingConfig } from '../../types/training'

/** Per target: the preset's blocks and estimate, VRAM per swapped block, musubi's maximum. */
const SWAP: Record<string, { baseBlocks: number; baseMb: number; perBlockMb: number; maxBlocks: number; perExtraBatchMb: number }> = {
  z_image: { baseBlocks: 8, baseMb: 8600, perBlockMb: 170, maxBlocks: 28, perExtraBatchMb: 1650 },
}

export function estimateVramMb(config: Pick<TrainingConfig, 'target' | 'blocks_to_swap' | 'estimated_vram_mb'> & { batch_size?: number }): number {
  const swap = SWAP[config.target]
  if (!swap) return config.estimated_vram_mb
  const blocks = Math.min(Math.max(config.blocks_to_swap, 0), swap.maxBlocks)
  const extraBatch = Math.max(0, (config.batch_size ?? 1) - 1) * swap.perExtraBatchMb
  return swap.baseMb - (blocks - swap.baseBlocks) * swap.perBlockMb + extraBatch
}

/**
 * About how long a run takes, in minutes, or null when unmeasured. MEASURED
 * 2026-10-02 (RTX 4070, musubi Z-Image): 2.3 s/step at 512 px, 4.9 at 768,
 * plus ~4 min to load the models and cache the dataset.
 */
export function estimateMinutes(config: Pick<TrainingConfig, 'target' | 'steps' | 'resolution'> & { batch_size?: number }): number | null {
  if (config.target !== 'z_image') return null
  // MEASURED 2026-10-02: a batch-2 step costs about 1.4x a batch-1 step at 512 px.
  const batchFactor = 1 + 0.4 * Math.max(0, (config.batch_size ?? 1) - 1)
  const secondsPerStep = 2.3 * Math.pow(Math.max(256, config.resolution) / 512, 2) * batchFactor
  return Math.round((config.steps * secondsPerStep) / 60 + 4)
}

export function maxBlocksToSwap(target: string): number | null {
  return SWAP[target]?.maxBlocks ?? null
}
