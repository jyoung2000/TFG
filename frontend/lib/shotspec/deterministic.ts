/**
 * Model-free image measurements — the TypeScript twin of
 * `backend/services/vision/deterministic.py` (both adapted from
 * macchant/imex-next, MIT: `pipeline/color.ts`, `pipeline/analyze.ts`).
 *
 * The renderer uses it for an instant preview while the server computes the
 * authoritative numbers that go into the ShotSpec. Same algorithm, same
 * constants, same seed, so the preview and the stored values agree.
 */

export interface PaletteEntry {
  hex: string
  share: number
}

export interface MeasuredStats {
  width: number
  height: number
  aspect: string
  palette: PaletteEntry[]
  luminance: number
  contrast: number
  saturation: number
  edge_density: number
  sharpness: number
  background_hex: string
  vector_likeness: number
}

const ANALYSIS_EDGE = 256
const PALETTE_K = 6
const ASPECTS: [string, number][] = [
  ['1:1', 1],
  ['4:3', 4 / 3],
  ['3:2', 3 / 2],
  ['16:9', 16 / 9],
  ['21:9', 21 / 9],
  ['9:16', 9 / 16],
  ['2:3', 2 / 3],
  ['3:4', 3 / 4],
  ['4:5', 4 / 5],
  ['5:4', 5 / 4],
]

export function snapAspect(width: number, height: number): string {
  const ratio = height ? width / height : 1
  let best: [string, number] = ASPECTS[0]
  let bestDistance = Infinity
  for (const entry of ASPECTS) {
    const distance = Math.abs(Math.log(ratio / entry[1]))
    if (distance < bestDistance) {
      bestDistance = distance
      best = entry
    }
  }
  return bestDistance < 0.08 ? best[0] : `${width}:${height}`
}

function srgbToLab(r: number, g: number, b: number): [number, number, number] {
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  const rl = lin(r), gl = lin(g), bl = lin(b)
  let x = (0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl) / 0.95047
  let y = 0.2126729 * rl + 0.7151522 * gl + 0.072175 * bl
  let z = (0.0193339 * rl + 0.119192 * gl + 0.9503041 * bl) / 1.08883
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116)
  x = f(x); y = f(y); z = f(z)
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)]
}

function labToHex(l: number, a: number, b: number): string {
  const fy = (l + 16) / 116
  const fx = fy + a / 500
  const fz = fy - b / 200
  const inv = (t: number) => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787)
  const x = inv(fx) * 0.95047, y = inv(fy), z = inv(fz) * 1.08883
  const lr = 3.2404542 * x - 1.5371385 * y - 0.4985314 * z
  const lg = -0.969266 * x + 1.8760108 * y + 0.041556 * z
  const lb = 0.0556434 * x - 0.2040259 * y + 1.0572252 * z
  const gamma = (c: number) => {
    const v = c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(Math.max(0, c), 1 / 2.4) - 0.055
    return Math.round(Math.min(1, Math.max(0, v)) * 255)
  }
  const toHex = (v: number) => v.toString(16).padStart(2, '0')
  return `#${toHex(gamma(lr))}${toHex(gamma(lg))}${toHex(gamma(lb))}`
}

/** numpy's PCG64 is not reproducible here; a small deterministic LCG picks the seeds instead. */
function makeRng(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 0x100000000
  }
}

/** k-means in CIELAB; deterministic (fixed seed, fixed iterations), largest cluster first. */
export function kmeansPalette(rgb: Float64Array, k = PALETTE_K, iterations = 12, seed = 7): PaletteEntry[] {
  const n = rgb.length / 3
  if (n === 0) return []
  const lab = new Float64Array(n * 3)
  for (let i = 0; i < n; i++) {
    const [l, a, b] = srgbToLab(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2])
    lab[i * 3] = l; lab[i * 3 + 1] = a; lab[i * 3 + 2] = b
  }
  k = Math.min(k, n)
  const rng = makeRng(seed)
  const chosen = new Set<number>()
  while (chosen.size < k) chosen.add(Math.floor(rng() * n))
  const centers = Array.from(chosen, i => [lab[i * 3], lab[i * 3 + 1], lab[i * 3 + 2]])
  const labels = new Int32Array(n)
  for (let iter = 0; iter < iterations; iter++) {
    for (let i = 0; i < n; i++) {
      let best = 0, bestD = Infinity
      for (let c = 0; c < k; c++) {
        const d = (lab[i * 3] - centers[c][0]) ** 2 + (lab[i * 3 + 1] - centers[c][1]) ** 2 + (lab[i * 3 + 2] - centers[c][2]) ** 2
        if (d < bestD) { bestD = d; best = c }
      }
      labels[i] = best
    }
    const sums = centers.map(() => [0, 0, 0, 0])
    for (let i = 0; i < n; i++) {
      const s = sums[labels[i]]
      s[0] += lab[i * 3]; s[1] += lab[i * 3 + 1]; s[2] += lab[i * 3 + 2]; s[3] += 1
    }
    for (let c = 0; c < k; c++) if (sums[c][3] > 0) centers[c] = [sums[c][0] / sums[c][3], sums[c][1] / sums[c][3], sums[c][2] / sums[c][3]]
  }
  const counts = new Array<number>(k).fill(0)
  for (let i = 0; i < n; i++) counts[labels[i]]++
  const order = counts.map((count, index) => [count, index]).sort((a, b) => b[0] - a[0])
  const total = n || 1
  return order.filter(([count]) => count > 0).map(([count, index]) => ({ hex: labToHex(centers[index][0], centers[index][1], centers[index][2]), share: Math.round((count / total) * 10000) / 10000 }))
}

function sobel(gray: Float64Array, width: number, height: number): Float64Array {
  const out = new Float64Array(width * height)
  const at = (x: number, y: number) => gray[Math.min(height - 1, Math.max(0, y)) * width + Math.min(width - 1, Math.max(0, x))]
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const gx = -at(x - 1, y - 1) + at(x + 1, y - 1) - 2 * at(x - 1, y) + 2 * at(x + 1, y) - at(x - 1, y + 1) + at(x + 1, y + 1)
      const gy = -at(x - 1, y - 1) - 2 * at(x, y - 1) - at(x + 1, y - 1) + at(x - 1, y + 1) + 2 * at(x, y + 1) + at(x + 1, y + 1)
      out[y * width + x] = Math.hypot(gx, gy)
    }
  }
  return out
}

function laplacianVariance(gray: Float64Array, width: number, height: number): number {
  const at = (x: number, y: number) => gray[Math.min(height - 1, Math.max(0, y)) * width + Math.min(width - 1, Math.max(0, x))]
  const values = new Float64Array(width * height)
  let mean = 0
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const v = at(x, y - 1) + at(x, y + 1) + at(x - 1, y) + at(x + 1, y) - 4 * at(x, y)
      values[y * width + x] = v
      mean += v
    }
  }
  mean /= values.length || 1
  let variance = 0
  for (const v of values) variance += (v - mean) ** 2
  return variance / (values.length || 1)
}

/** Nearest-neighbour downscale of RGBA pixels so the analysis matches the server's 256 px thumbnail. */
function downscale(rgba: Uint8ClampedArray, width: number, height: number): { rgb: Float64Array; w: number; h: number } {
  const scale = Math.min(1, ANALYSIS_EDGE / Math.max(width, height))
  const w = Math.max(1, Math.round(width * scale))
  const h = Math.max(1, Math.round(height * scale))
  const rgb = new Float64Array(w * h * 3)
  for (let y = 0; y < h; y++) {
    const sy = Math.min(height - 1, Math.floor((y + 0.5) / scale))
    for (let x = 0; x < w; x++) {
      const sx = Math.min(width - 1, Math.floor((x + 0.5) / scale))
      const i = (sy * width + sx) * 4
      const o = (y * w + x) * 3
      rgb[o] = rgba[i] / 255; rgb[o + 1] = rgba[i + 1] / 255; rgb[o + 2] = rgba[i + 2] / 255
    }
  }
  return { rgb, w, h }
}

/** Measure raw RGBA pixels (what `canvas.getImageData` returns). Pure; usable in tests without a DOM. */
export function measurePixels(rgba: Uint8ClampedArray, width: number, height: number): MeasuredStats {
  const { rgb, w, h } = downscale(rgba, width, height)
  const n = w * h
  const gray = new Float64Array(n)
  let lumSum = 0, satSum = 0
  for (let i = 0; i < n; i++) {
    const r = rgb[i * 3], g = rgb[i * 3 + 1], b = rgb[i * 3 + 2]
    gray[i] = 0.2126 * r + 0.7152 * g + 0.0722 * b
    lumSum += gray[i]
    const max = Math.max(r, g, b), min = Math.min(r, g, b)
    satSum += max === 0 ? 0 : (max - min) / max
  }
  const luminance = lumSum / n
  let varSum = 0
  for (let i = 0; i < n; i++) varSum += (gray[i] - luminance) ** 2
  const contrast = Math.sqrt(varSum / n)
  const edges = sobel(gray, w, h)
  let edgeCount = 0, hardCount = 0
  for (const e of edges) {
    if (e > 0.25) edgeCount++
    if (e > 1.0) hardCount++
  }
  const edgeDensity = edgeCount / n
  const sharpness = laplacianVariance(gray, w, h)

  // Background from the border ring.
  const ringLab: [number, number, number][] = []
  const pushLab = (x: number, y: number) => {
    const i = (y * w + x) * 3
    ringLab.push(srgbToLab(rgb[i], rgb[i + 1], rgb[i + 2]))
  }
  for (let x = 0; x < w; x++) { pushLab(x, 0); pushLab(x, h - 1) }
  for (let y = 0; y < h; y++) { pushLab(0, y); pushLab(w - 1, y) }
  const mean = [0, 0, 0]
  for (const l of ringLab) { mean[0] += l[0]; mean[1] += l[1]; mean[2] += l[2] }
  mean[0] /= ringLab.length; mean[1] /= ringLab.length; mean[2] /= ringLab.length
  const spread = [0, 0, 0]
  for (const l of ringLab) { spread[0] += (l[0] - mean[0]) ** 2; spread[1] += (l[1] - mean[1]) ** 2; spread[2] += (l[2] - mean[2]) ** 2 }
  const ringSpread = (Math.sqrt(spread[0] / ringLab.length) + Math.sqrt(spread[1] / ringLab.length) + Math.sqrt(spread[2] / ringLab.length)) / 3
  const backgroundHex = ringSpread < 6 ? labToHex(mean[0], mean[1], mean[2]) : ''

  const unique = new Set<number>()
  for (let i = 0; i < n; i++) unique.add((Math.round(rgb[i * 3] * 15) << 8) | (Math.round(rgb[i * 3 + 1] * 15) << 4) | Math.round(rgb[i * 3 + 2] * 15))
  const colourTerm = Math.max(0, 1 - unique.size / 400)
  const hardEdgeTerm = hardCount / Math.max(1, edgeCount)
  const vectorLikeness = Math.round(Math.min(1, 0.6 * colourTerm + 0.4 * hardEdgeTerm) * 1000) / 1000

  const round4 = (v: number) => Math.round(v * 10000) / 10000
  return {
    width,
    height,
    aspect: snapAspect(width, height),
    palette: kmeansPalette(rgb),
    luminance: round4(luminance),
    contrast: round4(contrast),
    saturation: round4(satSum / n),
    edge_density: round4(edgeDensity),
    sharpness: Math.round(sharpness * 1e6) / 1e6,
    background_hex: backgroundHex,
    vector_likeness: vectorLikeness,
  }
}

/** Measure a loaded image element via an offscreen canvas. */
export function measureImageElement(image: HTMLImageElement): MeasuredStats {
  const canvas = document.createElement('canvas')
  const scale = Math.min(1, ANALYSIS_EDGE / Math.max(image.naturalWidth, image.naturalHeight))
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
  const context = canvas.getContext('2d')
  if (!context) throw new Error('2D canvas unavailable')
  context.drawImage(image, 0, 0, canvas.width, canvas.height)
  const data = context.getImageData(0, 0, canvas.width, canvas.height).data
  const stats = measurePixels(data, canvas.width, canvas.height)
  return { ...stats, width: image.naturalWidth, height: image.naturalHeight, aspect: snapAspect(image.naturalWidth, image.naturalHeight) }
}
