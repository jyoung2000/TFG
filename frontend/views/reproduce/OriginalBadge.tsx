/**
 * The one marker that says which side of a comparison is the user's original
 * and which one the app rendered, used by image and video reproduce alike.
 */
export function MediaBadge({ kind }: { kind: 'original' | 'reproduction' }) {
  const original = kind === 'original'
  return (
    <span
      className={`absolute left-1.5 top-1.5 z-10 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider shadow ${original ? 'bg-teal-500 text-black' : 'bg-violet-600 text-white'}`}
      data-testid={`badge-${kind}`}
    >
      {original ? 'Original' : 'Reproduction'}
    </span>
  )
}

const MODEL_NAMES: Record<string, string> = {
  'vace_1.3B': 'VACE 1.3B (Wan 2.1)',
  ti2v_2_2_fastwan: 'FastWan 2.2 5B',
  ltx2_22B_distilled: 'LTX-2 22B distilled',
  'ltx2-fast': 'LTX-2 fast',
  'ltx2-pro': 'LTX-2 pro',
  flux2_klein_4b: 'FLUX.2 Klein 4B',
  z_image: 'Z-Image',
}

/** A model id as people read it; unknown ids pass through unchanged. */
export function modelName(id: string): string {
  return MODEL_NAMES[id] ?? id
}

const STRATEGY_NAMES: Record<string, string> = {
  start_frame: 'from the first frame',
  start_end_frames: 'from the first + last frames',
  reference_video: 'guided by the original clip',
}

export function strategyName(id: string | undefined): string {
  return id ? (STRATEGY_NAMES[id] ?? id) : ''
}
