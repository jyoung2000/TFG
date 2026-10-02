/**
 * The run's VRAM estimate as Block swap changes (QA pass 2026-10-02): the
 * Train screen showed a fixed number, so raising Block swap looked useless.
 * Mirrors backend `film/training_presets.estimate_vram_mb` - keep in sync:
 * the backend's figure is the one the run is held to.
 */

import type { TrainingConfig } from '../../types/training'

/** Per target: the preset's blocks and estimate, VRAM per swapped block, musubi's maximum. */
const SWAP: Record<string, { baseBlocks: number; baseMb: number; perBlockMb: number; maxBlocks: number }> = {
  z_image: { baseBlocks: 8, baseMb: 10500, perBlockMb: 205, maxBlocks: 28 },
}

export function estimateVramMb(config: Pick<TrainingConfig, 'target' | 'blocks_to_swap' | 'estimated_vram_mb'>): number {
  const swap = SWAP[config.target]
  if (!swap) return config.estimated_vram_mb
  const blocks = Math.min(Math.max(config.blocks_to_swap, 0), swap.maxBlocks)
  return swap.baseMb - (blocks - swap.baseBlocks) * swap.perBlockMb
}

export function maxBlocksToSwap(target: string): number | null {
  return SWAP[target]?.maxBlocks ?? null
}
