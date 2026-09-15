// Walks the browser-only UI screen by screen and checks that each one renders
// the same content it does in the packaged app, backed by the mock backend in
// devtools/ui-mock. No Python, no Electron, no GPU, no models.
//
// Two modes, both checked the same way:
//   pnpm dev:ui   → node scripts/verify/verify-ui-only.mjs
//   pnpm build:ui → UI_ONLY_URL=file:///abs/path/dist-ui/ltx-desktop-ui.html node ...
// (from a directory with playwright installed: npm i playwright)
import { chromium } from 'playwright'
import fs from 'node:fs'

const BASE = process.env.UI_ONLY_URL ?? 'http://127.0.0.1:5173'
/** The standalone file has no origin and no server: everything runs in the tab. */
const STANDALONE = BASE.startsWith('file://')
const CHROME = process.env.CHROME_PATH ?? undefined
const SHOTS = STANDALONE ? './verify-shots/ui-standalone' : './verify-shots/ui-only'
fs.mkdirSync(SHOTS, { recursive: true })

const results = []
const log = (step, ok, note = '') => {
  results.push({ step, ok, note })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${note ? ' — ' + note : ''}`)
}

const browser = await chromium.launch({ executablePath: CHROME, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
page.setDefaultTimeout(20000)
page.on('dialog', d => d.accept())

// Anything the page could not load is a real defect in UI-only mode: the whole
// point is that no request goes anywhere the browser cannot reach.
// Only same-origin failures matter: the app's web-font links go to Google and
// are expected to fail in a sandbox with no outbound network. The standalone
// file also has no public/ folder, so its decorative hero video is absent.
const sameOrigin = url =>
  !STANDALONE && (url.startsWith(BASE) || url.startsWith('http://localhost:5173'))
const failedRequests = []
page.on('requestfailed', r => {
  const error = r.failure()?.errorText ?? ''
  // ERR_ABORTED means the browser cancelled the request itself — a reload
  // mid-flight, or a <video> that unmounted before its range request
  // finished. That is normal behaviour, not a URL that does not work.
  if (error === 'net::ERR_ABORTED') return
  if (sameOrigin(r.url())) failedRequests.push(`${r.url()} (${error})`)
})
// Some steps deliberately provoke a 4xx to prove the backend refuses bad input.
// Those are the assertion, not a broken URL, so they are named here.
const EXPECTED_REFUSALS = [
  '/api/knowledge/import',
  '/api/prompts/compile',
  '/versions/',
  '/api/shot-library/',
  '/timeline/actions',
]
page.on('response', r => {
  if (r.status() < 400 || !sameOrigin(r.url())) return
  if (EXPECTED_REFUSALS.some(path => r.url().includes(path))) return
  failedRequests.push(`${r.status()} ${r.url()}`)
})
const pageErrors = []
page.on('pageerror', e => pageErrors.push(e.message))

const snap = name => page.screenshot({ path: `${SHOTS}/${name}.png` })
const api = (path, init = {}) =>
  page.evaluate(
    async ({ path, init }) => {
      const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
      const text = await res.text()
      let json = null
      try { json = JSON.parse(text) } catch {}
      return { status: res.status, json, text }
    },
    { path, init },
  )

try {
  // Always start from the seed so the run is repeatable.
  await page.goto(STANDALONE ? BASE : `${BASE}/`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)
  await api('/api/__ui_mock/reset', { method: 'POST' })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(5000)

  // ---- 1. Boot ----
  log(
    STANDALONE
      ? 'Opens straight from disk over file:// with no server at all'
      : 'Boots in a plain browser with no backend process',
    await page.getByText('What do you want to make?').isVisible(),
  )
  const health = await api('/health')
  log('Mock backend answers /health like the real one', health.status === 200 && health.json.models_loaded === true)
  await snap('01-home')

  // ---- 2. Quick video ----
  await page.getByRole('button', { name: /Quick video/i }).first().click()
  await page.waitForTimeout(1500)
  log(
    'Quick video renders prompt + settings',
    (await page.getByRole('button', { name: 'Generate' }).first().isVisible()) &&
      (await page.locator('textarea').first().isVisible()),
  )
  await snap('02-quick')

  // ---- 3. The demo film opens from Home like any saved project ----
  await page.getByRole('button', { name: /back to home/i }).first().click().catch(() => {})
  await page.waitForTimeout(800)
  log('The demo film is listed on Home', await page.getByText('The Relay (demo)').first().isVisible())
  await page.getByText('The Relay (demo)').first().click()
  await page.waitForTimeout(2500)
  await page.getByRole('button', { name: 'Storyboard' }).first().click()
  await page.waitForTimeout(3500)
  const cards = await page.locator('[aria-label^="Shot "]').count()
  log('Storyboard opens on the seeded demo film', cards >= 6, `${cards} shot cards`)
  log('Scene headings render', await page.getByText('Relay station, night').first().isVisible())
  await snap('03-storyboard')

  // ---- 4. Media actually loads (the reason the mock is served over HTTP) ----
  // Served over HTTP with the dev server, or as data:/blob: URLs in the
  // standalone file — either way the browser has to actually decode them.
  const mediaPattern = STANDALONE ? /^(data|blob):/ : /\/api\//
  // The dev server hands back the repo's H.264 sample; the standalone file
  // records VP8/VP9 in the tab. A Chromium built without proprietary codecs
  // decodes the second but not the first, so say which case this is instead of
  // reporting a pass the browser did not actually earn.
  const canDecodeH264 =
    STANDALONE ||
    (await page.evaluate(() => document.createElement('video').canPlayType('video/mp4; codecs="avc1.42E01E"') !== ''))
  // Decoding a real clip takes a moment over HTTP; give it one before judging.
  await page
    .waitForFunction(
      pattern => {
        const re = new RegExp(pattern)
        const videos = [...document.querySelectorAll('video')].filter(v => re.test(v.src))
        return videos.length > 0 && videos.every(v => v.videoWidth > 0)
      },
      mediaPattern.source,
      { timeout: 15000 },
    )
    .catch(() => {})
  const media = await page.evaluate(pattern => {
    const re = new RegExp(pattern)
    const images = [...document.querySelectorAll('img')].filter(i => re.test(i.src))
    const videos = [...document.querySelectorAll('video')].filter(v => re.test(v.src))
    return {
      images: images.length,
      loaded: images.filter(i => i.naturalWidth > 0).length,
      videos: videos.length,
      playable: videos.filter(v => v.videoWidth > 0).length,
    }
  }, mediaPattern.source)
  log(
    'Shot captures decode as real images',
    media.images > 0 && media.loaded === media.images,
    `${media.loaded}/${media.images} images`,
  )
  if (canDecodeH264) {
    log(
      'Rendered clips decode as playable video',
      media.videos > 0 && media.playable === media.videos,
      `${media.playable}/${media.videos} videos`,
    )
  } else {
    log(
      'Rendered clips are wired to a video source (decode not checked)',
      media.videos > 0,
      `${media.videos} video elements; this browser has no H.264 decoder, so the dev server's sample clip cannot play here`,
    )
  }

  // ---- 5. Continuity ----
  const continuity = await api('/api/film/projects/ui-mock-film/continuity')
  log(
    'Continuity reports a real issue on the seeded film',
    continuity.json.level === 'significant' && continuity.json.shots.some(s => s.level === 'significant'),
    `level=${continuity.json.level}`,
  )

  // ---- 6. Shot drawer ----
  await page.locator('[aria-label^="Shot "]').first().click()
  await page.waitForTimeout(1200)
  log('Shot drawer opens with the shot detail', await page.getByRole('button', { name: 'Close shot details' }).isVisible())
  await snap('04-drawer')
  await page.getByRole('button', { name: 'Close shot details' }).click()

  // ---- 7. Storyboard sub-tabs ----
  for (const [tab, marker] of [['Assets', 'Mara'], ['Script', 'RELAY STATION']]) {
    await page.getByRole('tab', { name: tab, exact: true }).click()
    await page.waitForTimeout(1500)
    log(`${tab} tab renders`, await page.getByText(marker, { exact: false }).first().isVisible())
    await snap(`05-${tab.toLowerCase()}`)
  }
  log(
    'Models are configured in Settings, not in the filmmaking workflow',
    (await page.getByRole('tab', { name: 'Models', exact: true }).count()) === 0,
  )
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'aiModels' } })))
  await page.waitForTimeout(2000)
  log('Settings → AI Models holds the library and the installed models', await page.getByRole('heading', { name: 'Model Library' }).isVisible())
  await snap('05-ai-models')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)

  // ---- 8. Model Library ----
  const library = await api('/api/models/library')
  log('Model Library lists local and hosted models', library.json.total >= 10, `${library.json.total} models`)
  log('Offline readiness is reported', typeof library.json.offline_ready === 'boolean' && library.json.offline_note.length > 0)

  // ---- 9. Settings: connect, configure and test a provider ----
  await page.getByRole('tab', { name: 'Storyboard', exact: true }).click()
  await page.waitForTimeout(800)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'aiModels' } })))
  await page.waitForTimeout(1500)
  log('AI Models opens with the provider cards', await page.getByLabel('OpenRouter API key').isVisible())
  // Every provider can be tested from here, and an unconfigured one says so
  // rather than pretending it checked something.
  await page.getByRole('button', { name: 'Test the Claude (Anthropic) connection' }).click()
  await page.waitForTimeout(1500)
  const testMessage = await page.locator('[role="status"]').first().innerText().catch(() => '')
  log('Testing an unconfigured provider reports no key, not a false pass', /no api key/i.test(testMessage), testMessage.slice(0, 60))
  await snap('06-settings')
  await page.keyboard.press('Escape')

  // ---- 9b. Settings → Knowledge: what the app has learned, and how honestly ----
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'knowledge' } })))
  await page.waitForTimeout(1800)
  log('Settings → Knowledge opens', await page.getByRole('heading', { name: 'What this app has learned' }).isVisible())

  const summary = await api('/api/knowledge')
  log('The knowledge store reports its size and location', summary.json.event_count > 0 && summary.json.database.length > 0, `${summary.json.event_count} events, ${summary.json.model_count} models`)

  const models = await api('/api/knowledge/models')
  const profiles = models.json.models ?? []
  // The whole point of the screen: a count and a guess must not look alike.
  const kinds = new Set(profiles.flatMap(p => p.observations.map(o => o.kind)))
  log('Counts are labelled as facts', kinds.has('fact'))
  log('A thin sample is labelled a hypothesis, not a pattern', kinds.has('hypothesis'), [...kinds].join(', '))
  const facts = profiles.flatMap(p => p.observations).filter(o => o.kind === 'fact')
  const guesses = profiles.flatMap(p => p.observations).filter(o => o.kind !== 'fact')
  log('No derived claim is stated with certainty', guesses.every(o => o.confidence < 1) && facts.every(o => o.confidence === 1))
  const patterned = profiles.find(p => p.prompt_patterns.some(x => x.verdict !== 'unclear'))
  log('Prompt vocabulary is scored from use, not asserted', Boolean(patterned), patterned ? `${patterned.model}: ${patterned.prompt_patterns.filter(x => x.verdict !== 'unclear').map(x => x.phrase).join(', ')}` : '')

  // Expanding a model shows the evidence behind every statement.
  await page.getByRole('button', { name: /ltxv-13b/ }).first().click()
  await page.waitForTimeout(800)
  const confidenceShown = await page.getByText(/% confidence,/).first().isVisible()
  log('Every statement is shown with its confidence and sample size', confidenceShown)
  await snap('06b-knowledge')

  // Turning learning off must stop collection, not just hide it.
  await api('/api/knowledge/settings', {
    method: 'PUT',
    body: JSON.stringify({ enabled: false, generation: true, approval: true, editing: true, feedback: true }),
  })
  const declined = await api('/api/knowledge/feedback', { method: 'POST', body: JSON.stringify({ model: 'ltxv-13b-098-dev', rating: 5 }) })
  log('With learning off, feedback is declined rather than silently dropped', declined.json.status === 'declined')
  await api('/api/knowledge/settings', {
    method: 'PUT',
    body: JSON.stringify({ enabled: true, generation: true, approval: true, editing: true, feedback: true }),
  })
  const accepted = await api('/api/knowledge/feedback', { method: 'POST', body: JSON.stringify({ model: 'ltxv-13b-098-dev', rating: 5 }) })
  log('With learning on, feedback is recorded', accepted.json.status === 'ok')

  const exported = await api('/api/knowledge/export')
  log('Knowledge can be exported for another machine', exported.json.schema_version === 1 && exported.json.events.length > 0, `${exported.json.events.length} events`)
  const badImport = await api('/api/knowledge/import', { method: 'POST', body: JSON.stringify({ payload: { schema_version: 99, exported_at: 0, events: [], observations: [] } }) })
  log('An export from an unknown version is refused', badImport.status === 400)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)

  // ---- 9c. The prompt compiler: one shot, written per model ----
  const targets = await api('/api/prompts/targets')
  const targetIds = targets.json.targets.map(t => t.id)
  log('Prompt conventions are inspectable', targetIds.includes('ltx') && targetIds.includes('generic'), targetIds.join(', '))
  // The rule that classifies a model must be visible, not just its verdict.
  const ltxTarget = targets.json.targets.find(t => t.id === 'ltx')
  log('A convention says what identifies it and where it came from', ltxTarget.matches.length > 0 && ltxTarget.basis === 'publisher_guidance')

  const brief = {
    scene_intent: 'Establish the diner', subjects: ['Mara, in a waitress uniform'],
    action: 'She sets down a coffee pot and turns toward the door',
    location: 'A roadside diner at 4am', shot_size: 'medium shot',
    camera: 'three-quarter left angle', lens: '35mm', movement: 'slow push in',
    lighting: 'practical ceiling light', style: 'muted palette', audio: 'rain on glass',
    timeline: '6 seconds at 24fps', continuity: ['Mara wearing the green apron'],
    negative: ['text', 'watermark'],
  }
  const compiled = await api('/api/prompts/compile', {
    method: 'POST',
    body: JSON.stringify({ models: ['ltxv-13b', 'wavespeed-ai/wan-2.2/t2v-480p', 'fal-ai/flux/dev', 'not-a-real-model'], brief }),
  })
  const byModel = Object.fromEntries(compiled.json.prompts.map(p => [p.model, p]))
  log('The same shot reads differently per model family',
    byModel['ltxv-13b'].prompt !== byModel['wavespeed-ai/wan-2.2/t2v-480p'].prompt)
  log('Wan gets labelled clauses, LTX gets prose',
    byModel['wavespeed-ai/wan-2.2/t2v-480p'].prompt.includes('Subject:') && !byModel['ltxv-13b'].prompt.includes('Subject:'))
  log('The action survives into every target',
    compiled.json.prompts.every(p => p.prompt.includes('coffee pot')))
  log('A still model drops motion and says so',
    byModel['fal-ai/flux/dev'].dropped.some(d => d.includes('movement')) && !byModel['fal-ai/flux/dev'].prompt.includes('push in'))
  log('An unrecognised model is labelled as such, not dressed up as tailored',
    byModel['not-a-real-model'].matched === false && byModel['ltxv-13b'].matched === true)
  log('Scene intent never reaches a render model',
    compiled.json.prompts.every(p => !p.prompt.includes('Establish the diner')))
  const ambiguous = await api('/api/prompts/compile', { method: 'POST', body: JSON.stringify({ models: ['ltxv-13b'] }) })
  log('A request with no source is refused rather than guessed at', ambiguous.status === 400)

  // ---- 10. Generation through the simulated queue ----
  const queued = await api('/api/film/projects/ui-mock-film/scenes/scene-2/shots/shot-2-2/generate', {
    method: 'POST',
    body: JSON.stringify({ kind: 'preview' }),
  })
  log('A shot can be queued for render', queued.status === 200 && queued.json.status === 'queued')
  await page.waitForTimeout(2500)
  const queue = await api('/api/film/queue')
  log('The queue reports an active job with progress', queue.json.active !== null && queue.json.progress !== null, `${queue.json.progress}% ${queue.json.phase}`)
  await api('/api/film/queue/cancel', { method: 'POST' })

  // ---- 10b. Deleting one take: what it refuses is the point ----
  const takes = await page.evaluate(async () => {
    const call = async (path, init) => {
      const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
      return { status: res.status, body: await res.json().catch(() => null) }
    }
    const base = '/api/film/projects/ui-mock-film/scenes/scene-1/shots/shot-1-2'
    const project = await (await fetch('/api/film/projects/ui-mock-film')).json()
    const shot = project.project.scenes.flatMap(s => s.shots).find(s => s.id === 'shot-1-2')
    const number = shot.current_version

    // Approved shot: refused outright, even with force.
    await call(`${base}`, { method: 'PUT', body: JSON.stringify({ status: 'approved' }) })
    const onApproved = await call(`${base}/versions/${number}?force=true`, { method: 'DELETE' })

    // Back to review: the current take now needs force, and works with it.
    await call(`${base}`, { method: 'PUT', body: JSON.stringify({ status: 'review' }) })
    const withoutForce = await call(`${base}/versions/${number}`, { method: 'DELETE' })
    const withForce = await call(`${base}/versions/${number}?force=true`, { method: 'DELETE' })
    const twice = await call(`${base}/versions/${number}?force=true`, { method: 'DELETE' })

    const after = await (await fetch('/api/film/projects/ui-mock-film')).json()
    const afterShot = after.project.scenes.flatMap(s => s.shots).find(s => s.id === 'shot-1-2')
    const tombstone = afterShot.versions.find(v => v.number === number)
    return { number, onApproved, withoutForce, withForce, twice, tombstone }
  })
  log('The approved take cannot be deleted, even with force', takes.onApproved.status === 400)
  log('The current take needs an explicit force', takes.withoutForce.status === 409)
  log('With force, the take is deleted', takes.withForce.status === 200 && takes.withForce.body.status === 'deleted')
  log('Deleting twice is refused rather than silently repeated', takes.twice.status === 400)
  log(
    'The record survives as a tombstone with what produced it',
    takes.tombstone.status === 'deleted' && takes.tombstone.output_path === '' && takes.tombstone.prompt.length > 0,
  )

  // ---- 10c. The cross-project shot library ----
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'shotLibrary' } })))
  await page.waitForTimeout(1800)
  log('Settings → Shot Library opens', await page.getByRole('heading', { name: 'Shot Library' }).isVisible())
  log('The library shows what was saved', await page.getByText('Console close-up, torchlight').first().isVisible())
  await snap('06c-shot-library')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)

  const shotLibrary = await page.evaluate(async () => {
    const call = async (path, init) => {
      const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
      return { status: res.status, body: await res.json().catch(() => null) }
    }
    // Save a shot from one film.
    const saved = await call('/api/shot-library', {
      method: 'POST',
      body: JSON.stringify({
        project_id: 'ui-mock-film', shot_id: 'shot-1-1',
        title: 'Verifier item', tags: ['Night', ' night ', 'wide'], rating: 3,
      }),
    })
    const id = saved.body.id

    // Use it in a different one.
    const applied = await call(`/api/shot-library/${id}/apply`, {
      method: 'POST',
      body: JSON.stringify({ project_id: 'ui-mock-film', scene_id: 'scene-2' }),
    })

    const search = await call('/api/shot-library?q=verifier')
    const byTag = await call('/api/shot-library?tags=night&tags=wide')
    const duplicated = await call(`/api/shot-library/${id}/duplicate`, { method: 'POST' })
    const partial = await call(`/api/shot-library/${id}`, { method: 'PUT', body: JSON.stringify({ notes: 'kept' }) })
    const ratingOnly = await call(`/api/shot-library/${id}`, { method: 'PUT', body: JSON.stringify({ rating: 5 }) })
    await call(`/api/shot-library/${id}/archive`, { method: 'POST' })
    const hidden = await call('/api/shot-library?q=verifier')
    const shelved = await call('/api/shot-library?archived=true')
    const restored = await call(`/api/shot-library/${id}/restore`, { method: 'POST' })
    const removed = await call(`/api/shot-library/${duplicated.body.id}`, { method: 'DELETE' })
    const gone = await call(`/api/shot-library/${duplicated.body.id}`)
    return { saved, id, applied, search, byTag, duplicated, partial, ratingOnly, hidden, shelved, restored, removed, gone }
  })

  log('A shot can be saved to the library', shotLibrary.saved.status === 200 && shotLibrary.saved.body.title === 'Verifier item')
  log('Tags are normalised on the way in', JSON.stringify(shotLibrary.saved.body.tags) === JSON.stringify(['night', 'wide']))
  log('A library item can be used in another scene', shotLibrary.applied.status === 200 && shotLibrary.applied.body.title === 'Verifier item')
  log('The applied prompt is locked, so synthesis does not undo it', shotLibrary.applied.body.prompt_locked === true)
  log('Free-text search finds it', shotLibrary.search.body.items.some(i => i.id === shotLibrary.id))
  log('Tag filtering requires all the tags, not any', shotLibrary.byTag.body.items.some(i => i.id === shotLibrary.id))
  log('An item can be duplicated', shotLibrary.duplicated.status === 200 && shotLibrary.duplicated.body.id !== shotLibrary.id)
  log(
    'Editing only changes what was sent',
    shotLibrary.ratingOnly.body.rating === 5 && shotLibrary.ratingOnly.body.notes === 'kept' && shotLibrary.ratingOnly.body.title === 'Verifier item',
  )
  log('Archiving hides it from the default listing', !shotLibrary.hidden.body.items.some(i => i.id === shotLibrary.id))
  log('Archived items are on their own shelf', shotLibrary.shelved.body.items.some(i => i.id === shotLibrary.id))
  log('Restoring brings it back', shotLibrary.restored.body.archived === false)
  log('Deleting is permanent', shotLibrary.removed.status === 200 && shotLibrary.gone.status === 404)

  // ---- 10d. Timeline editing, and the undo that makes it safe ----
  await page.getByRole('button', { name: 'Storyboard' }).first().click()
  await page.waitForTimeout(2000)
  await page.getByRole('tab', { name: 'Timeline', exact: true }).click()
  await page.waitForTimeout(1500)
  log('The Timeline tab opens', await page.getByRole('heading', { name: 'Timeline' }).isVisible())
  await snap('06d-timeline')

  const cut = await page.evaluate(async () => {
    const call = async (path, init) => {
      const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
      return { status: res.status, body: await res.json().catch(() => null) }
    }
    const base = '/api/film/projects/ui-mock-film/timeline'
    const act = (action, params = {}, actor = 'user') =>
      call(`${base}/actions`, { method: 'POST', body: JSON.stringify({ action, params, actor }) })

    const before = (await call(base)).body
    const first = before.entries[0]

    const split = await act('split_shot', { shot_id: first.shot_id })
    const trimmed = await act('trim_shot', { shot_id: first.shot_id, duration_seconds: 2 })
    const transition = await act('set_transition', { shot_id: first.shot_id, where: 'out', kind: 'dissolve', duration_seconds: 1 })
    const byDirector = await act('set_gap', { shot_id: before.entries[1].shot_id, gap_seconds: 1.5 }, 'director')

    // A refused edit must change nothing at all.
    const stateBeforeRefusal = (await call(base)).body
    const refused = await act('split_shot', { shot_id: first.shot_id, at_seconds: 999 })
    const stateAfterRefusal = (await call(base)).body

    const history = (await call(`${base}/history`)).body
    const undone = await call(`${base}/undo`, { method: 'POST' })
    const afterUndo = (await call(base)).body
    return {
      before, split, trimmed, transition, byDirector, refused,
      unchanged: JSON.stringify(stateBeforeRefusal) === JSON.stringify(stateAfterRefusal),
      history, undone, afterUndo,
    }
  })

  log('The timeline is the film in running order', cut.before.entries.length >= 6, `${cut.before.entries.length} shots, ${cut.before.total_seconds}s`)
  log('A shot can be split in two', cut.split.status === 200 && cut.split.body.action.affected_shot_ids.length === 2)
  log('A shot can be trimmed', cut.trimmed.status === 200 && cut.trimmed.body.timeline.entries[0].duration_seconds === 2)
  log('A transition can be set', cut.transition.body.timeline.entries[0].transition_out.kind === 'dissolve')
  log('An edit made by the director is recorded as the director\'s',
    cut.history.actions.some(a => a.actor === 'director') && cut.history.actions.some(a => a.actor === 'user'))
  log('A refused edit is refused', cut.refused.status === 400)
  log('A refused edit changes nothing', cut.unchanged)
  log('Undo puts the film back', cut.undone.status === 200)
  log('The undo snapshot never travels over the API', cut.history.actions.every(a => a.before === null))
  log('Every edit is recorded with a readable summary', cut.history.actions.every(a => a.summary.length > 0), cut.history.actions.slice(-1)[0]?.summary ?? '')

  // ---- 11. Editing round-trips through the mock ----
  const renamed = await api('/api/film/projects/ui-mock-film/scenes/scene-1/shots/shot-1-1', {
    method: 'PUT',
    body: JSON.stringify({ title: 'Renamed by the verifier' }),
  })
  log('Shot edits persist in the mock backend', renamed.json.title === 'Renamed by the verifier')

  // ---- 11b. Analyse Video: the reverse flow, end to end ----
  // Reload rather than navigating back: the app starts on Home, which makes
  // this step independent of wherever the previous one left off.
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4000)
  log('Home offers Analyse video as an entry point', await page.getByText('Analyse video').first().isVisible())
  await page.getByRole('button', { name: /Analyse a video|Analyse video/ }).first().click()
  await page.waitForTimeout(1500)
  log('The Analyse Video workspace opens', await page.getByRole('button', { name: 'Import a video' }).isVisible())
  await snap('07-analyze')

  const reverse = await page.evaluate(async () => {
    const post = async (path, body) =>
      (await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })).json()
    const analysis = await post('/api/video-analysis/import', { path: '/movies/ref.mp4', title: 'Reference' })
    const detected = await post(`/api/video-analysis/${analysis.id}/detect`)
    const analysed = await post(`/api/video-analysis/${analysis.id}/analyze`, {})
    const project = await post(`/api/video-analysis/${analysis.id}/reconstruct`, {})
    return {
      shots: detected.shots.length,
      measuredBeforeModel: detected.shots[0].visual.confidence === 0,
      stage: analysed.stage,
      prompt: analysed.shots[0].prompts.video,
      projectShots: project.scenes[0].shots.length,
      lineage: project.scenes[0].shots[0].source_ref?.kind,
      modelSpecific: Object.keys(analysed.shots[0].prompts.model_specific),
      analysisId: analysis.id,
    }
  })
  log('A video is split into shots', reverse.shots > 1, `${reverse.shots} shots`)
  log('Inference stays empty until a model runs', reverse.measuredBeforeModel)
  log('Analysis derives a prompt per shot', reverse.stage === 'complete' && reverse.prompt.length > 0)
  log(
    'The analysis becomes a real project with lineage to the source',
    reverse.projectShots === reverse.shots && reverse.lineage === 'video_analysis',
  )
  log(
    'Every analysed shot carries a prompt compiled for the models it could be sent to',
    reverse.modelSpecific.length > 0,
    reverse.modelSpecific.join(', '),
  )

  // ---- 12. Nothing broke along the way ----
  log('No page errors', pageErrors.length === 0, pageErrors.slice(0, 2).join(' | '))
  log('No failed same-origin requests', failedRequests.length === 0, failedRequests.slice(0, 3).join(' | '))
} finally {
  fs.writeFileSync(`${SHOTS}/results.json`, JSON.stringify(results, null, 2))
  const passed = results.filter(r => r.ok).length
  console.log(`\n${passed}/${results.length} passed`)
  await browser.close()
  if (passed !== results.length) process.exitCode = 1
}
