/**
 * Turn backend error strings (which carry stable codes like
 * OPENROUTER_KEY_INVALID) into something a person can act on.
 */

export type ErrorAction = 'open-api-keys' | 'open-ai-models' | 'open-models' | 'retry' | null

export interface FriendlyError {
  title: string
  detail: string
  action: ErrorAction
  actionLabel: string
}

const RULES: { match: RegExp; title: string; detail: string; action: ErrorAction; actionLabel: string }[] = [
  // Media providers first: their keys live in Settings -> AI Models, not the
  // API Keys tab, and their codes would otherwise fall through to the generic
  // rules below (or to the raw-code default).
  {
    match: /(FAL|WAVESPEED|REPLICATE)_KEY_MISSING/,
    title: 'No key for this cloud provider',
    detail:
      'This project generates on a hosted provider, but no key is stored for it. Add one in Settings → AI Models, or switch the project back to generating on this computer.',
    action: 'open-ai-models',
    actionLabel: 'Open AI Models',
  },
  {
    match: /(FAL|WAVESPEED|REPLICATE)_KEY_INVALID/,
    title: 'The cloud provider rejected the API key',
    detail: 'The stored key is invalid or was revoked. Replace it in Settings → AI Models.',
    action: 'open-ai-models',
    actionLabel: 'Fix key',
  },
  {
    match: /(FAL|WAVESPEED|REPLICATE)_CREDITS/,
    title: 'Cloud provider credits exhausted',
    detail:
      'The provider reports no credits left. Top up with the provider, or switch this project to another provider or to local generation in Settings → AI Models.',
    action: 'open-ai-models',
    actionLabel: 'Open AI Models',
  },
  {
    match: /MEDIA_MODEL_PROVIDER_MISMATCH/,
    title: 'That model belongs to a different provider',
    detail:
      'The selected model id was issued by another cloud provider, so this one would reject it. Pick a model from the provider this project is set to in the Model Library.',
    action: 'open-ai-models',
    actionLabel: 'Open AI Models',
  },
  {
    match: /(FAL|WAVESPEED|REPLICATE)_MODEL_NOT_FOUND/,
    title: 'Model not available on this provider',
    detail: 'The model id set for this project no longer exists there. Pick another one in the Model Library.',
    action: 'open-ai-models',
    actionLabel: 'Pick model',
  },
  {
    match: /WAVESPEED_IMAGE_TOO_LARGE/,
    title: 'Reference frame too large',
    detail: 'WaveSpeed accepts reference images up to 200 MB. Use a smaller capture or a lower resolution.',
    action: null,
    actionLabel: '',
  },
  {
    match: /AI_DIRECTOR_KEY_MISSING|OPENROUTER_KEY_MISSING|GEMINI_API_KEY_MISSING|OPENAI_COMPATIBLE_NOT_CONFIGURED/,
    title: 'No AI provider configured',
    detail:
      'Connect a text model in Settings → AI Models: an OpenRouter, Claude, Grok or Gemini key, or a local OpenAI-compatible server (LM Studio, Ollama) for a fully offline director. Offline features keep working without one.',
    action: 'open-ai-models',
    actionLabel: 'Open AI Models',
  },
  {
    match: /OPENROUTER_KEY_INVALID|GEMINI_KEY_INVALID/,
    title: 'The AI provider rejected the API key',
    detail: 'The stored key is invalid or was revoked. Remove it in Settings → AI Models and add a valid key.',
    action: 'open-ai-models',
    actionLabel: 'Fix key',
  },
  {
    match: /OPENROUTER_CREDITS/,
    title: 'OpenRouter credits exhausted',
    detail: 'Top up credits at openrouter.ai or choose a free model for this role in Settings → AI Models.',
    action: 'open-ai-models',
    actionLabel: 'Choose model',
  },
  {
    match: /OPENROUTER_MODEL_NOT_FOUND/,
    title: 'Model not available on OpenRouter',
    detail: 'The model id set for this role no longer exists. Pick another one from the model list in Settings → AI Models.',
    action: 'open-ai-models',
    actionLabel: 'Pick model',
  },
  {
    match: /OPENROUTER_RATE_LIMITED|429/,
    title: 'Rate limited',
    detail: 'The provider is throttling requests. Wait a moment and try again.',
    action: 'retry',
    actionLabel: 'Retry',
  },
  {
    match: /timed out/i,
    title: 'The request timed out',
    detail: 'The provider did not answer in time. Try again, or pick a faster model for this role.',
    action: 'retry',
    actionLabel: 'Retry',
  },
  {
    match: /PRO_API_KEY_REQUIRED/,
    title: 'LTX API key required',
    detail: 'Cloud generation needs an LTX API key. Add it in Settings → API Keys.',
    action: 'open-api-keys',
    actionLabel: 'Open API Keys',
  },
  {
    match: /No module named 'mmgp'|No module named 'wgp'|WanGP bridge .*not available|WanGP .*unavailable/i,
    title: 'WanGP bridge dependencies are missing',
    detail: 'The backend found a Wan2GP checkout but its Python packages are not installed. Install Wan2GP/requirements.txt into the backend Python (setup-dev.ps1 does this on Windows), or unset WANGP_ROOT to use API mode.',
    action: 'open-models',
    actionLabel: 'Open Models',
  },
  {
    match: /Models not downloaded/i,
    title: 'Models are not downloaded yet',
    detail: 'Download the required models first (Storyboard → Models shows what fits your GPU).',
    action: 'open-models',
    actionLabel: 'Open Models',
  },
  {
    match: /Generation already in progress|already queued or generating/i,
    title: 'Generation is busy',
    detail: 'One generation runs at a time; new shots wait in the production queue.',
    action: null,
    actionLabel: '',
  },
  {
    match: /out of memory|CUDA error|OOM/i,
    title: 'The GPU ran out of memory',
    detail: 'Lower the resolution or duration, pick the Fast Preview profile, or close other GPU applications.',
    action: 'open-models',
    actionLabel: 'Quality profiles',
  },
  {
    match: /Strict continuity is enabled/i,
    title: 'Blocked by strict continuity',
    detail: 'Fix the continuity warnings in the shot drawer, or turn strict continuity off in Storyboard → Models → Project render defaults.',
    action: null,
    actionLabel: '',
  },
]

export function describeError(raw: unknown): FriendlyError {
  const message = raw instanceof Error ? raw.message : typeof raw === 'string' ? raw : String(raw ?? 'Unknown error')
  for (const rule of RULES) {
    if (rule.match.test(message)) {
      return { title: rule.title, detail: rule.detail, action: rule.action, actionLabel: rule.actionLabel }
    }
  }
  return { title: 'Something went wrong', detail: message, action: null, actionLabel: '' }
}

/** Ask the app shell to open Settings on a tab (handled in App.tsx). */
export function requestSettings(
  tab: 'apiKeys' | 'aiModels' | 'general' | 'inference' | 'about' = 'apiKeys',
): void {
  window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab } }))
}
