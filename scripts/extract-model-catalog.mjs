// Extract a compact capability catalog from Anil-matcha/Open-Generative-AI's
// packages/studio/src/models.js (MIT) → backend/film/data/model_catalog.json.
// Only structural facts survive: id, name, vendor, task, and which inputs the
// model accepts. Provider endpoints and marketing fields are dropped.
//
//   node scripts/extract-model-catalog.mjs <path-to-Open-Generative-AI>
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const root = process.argv[2]
if (!root) throw new Error('usage: extract-model-catalog.mjs <Open-Generative-AI checkout>')
const source = path.join(root, 'packages/studio/src/models.js')
let text = fs.readFileSync(source, 'utf8')
// The file imports app-local helpers; stub them so the tables evaluate standalone.
text = text.replace(/^import[\s\S]*?from ['"][^'"]+['"];?\n/gm, '')
const stub = `const getMediaCapability = () => ({}); const getAspectRatioOptions = () => []; const I2I_DIMENSION_RATIOS = []; const T2I_DIMENSION_RATIOS = [];\n`
const tmp = path.join(process.cwd(), '.catalog-tmp.mjs')
fs.writeFileSync(tmp, stub + text)
const mod = await import(pathToFileURL(tmp).href)
fs.unlinkSync(tmp)
const tasks = { t2iModels: 't2i', t2vModels: 't2v', i2iModels: 'i2i', i2vModels: 'i2v', v2vModels: 'v2v' }
const rows = []
for (const [key, task] of Object.entries(tasks)) {
  for (const model of mod[key] ?? []) {
    const inputs = model.inputs ?? {}
    const pick = name => inputs[name]
    const enumOf = name => (Array.isArray(pick(name)?.enum) ? pick(name).enum.map(String) : [])
    const duration = pick('duration')
    rows.push({
      id: String(model.id),
      name: String(model.name ?? model.id),
      vendor: String(model.provider ?? ''),
      task,
      image_input: Boolean(pick('image') || pick('image_url') || pick('images') || pick('image_urls') || task === 'i2i' || task === 'i2v'),
      video_input: Boolean(pick('video') || pick('video_url') || task === 'v2v'),
      edit: /edit|kontext|inpaint|banana/i.test(String(model.id)) || Boolean(pick('mask') || pick('mask_url')),
      negative_prompt: Boolean(pick('negative_prompt')),
      seed: Boolean(pick('seed')),
      aspect_ratios: enumOf('aspect_ratio'),
      resolutions: enumOf('resolution'),
      duration: duration ? { min: duration.minValue ?? null, max: duration.maxValue ?? null, default: duration.default ?? null, options: enumOf('duration') } : null,
    })
  }
}
const out = path.join(process.cwd(), 'backend/film/data/model_catalog.json')
fs.mkdirSync(path.dirname(out), { recursive: true })
fs.writeFileSync(out, JSON.stringify({ source: 'Anil-matcha/Open-Generative-AI packages/studio/src/models.js (MIT)', extracted: new Date().toISOString().slice(0, 10), models: rows }, null, 1) + '\n')
console.log(`wrote ${rows.length} models to ${path.relative(process.cwd(), out)}`)
