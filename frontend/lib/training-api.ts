import { backendFetch, getBackendCredentials } from './backend'
import { mediaResolver } from './media-resolver'
import type {
  Dataset,
  DatasetPreset,
  ImportDatasetItemsRequest,
  LoraEntry,
  StartTrainingRequest,
  TrainingConfig,
  TrainingRun,
  TrainingStatusResponse,
} from '../types/training'

const enc = encodeURIComponent

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await backendFetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body?.error === 'string' ? body.error : typeof body?.message === 'string' ? body.message : JSON.stringify(body)
    } catch {
      detail = await response.text().catch(() => '')
    }
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return (await response.json()) as T
}

export const trainingApi = {
  status: () => request<TrainingStatusResponse>('/api/training/status'),
  setWeights: (target: string, values: Record<string, string>) =>
    request<Record<string, Record<string, string>>>(`/api/training/weights/${enc(target)}`, { method: 'PUT', body: JSON.stringify(values) }),

  listDatasets: () => request<{ datasets: Dataset[] }>('/api/training/datasets').then(r => r.datasets),
  getDataset: (id: string) => request<Dataset>(`/api/training/datasets/${enc(id)}`),
  createDataset: (data: { name: string; preset: DatasetPreset; trigger: string }) =>
    request<Dataset>('/api/training/datasets', { method: 'POST', body: JSON.stringify(data) }),
  updateDataset: (id: string, data: Partial<Pick<Dataset, 'name' | 'preset' | 'trigger'>>) =>
    request<Dataset>(`/api/training/datasets/${enc(id)}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteDataset: (id: string) => request<{ status: string }>(`/api/training/datasets/${enc(id)}`, { method: 'DELETE' }),
  importItems: (id: string, data: ImportDatasetItemsRequest) =>
    request<Dataset>(`/api/training/datasets/${enc(id)}/import`, { method: 'POST', body: JSON.stringify(data) }),
  caption: (id: string, overwriteEdited = false) =>
    request<Dataset>(`/api/training/datasets/${enc(id)}/caption`, { method: 'POST', body: JSON.stringify({ overwrite_edited: overwriteEdited }) }),
  updateItem: (id: string, itemId: string, caption: string) =>
    request<Dataset>(`/api/training/datasets/${enc(id)}/items/${enc(itemId)}`, { method: 'PUT', body: JSON.stringify({ caption }) }),
  removeItem: (id: string, itemId: string) => request<Dataset>(`/api/training/datasets/${enc(id)}/items/${enc(itemId)}`, { method: 'DELETE' }),

  suggest: (datasetId: string, target: string) =>
    request<TrainingConfig>('/api/training/suggest', { method: 'POST', body: JSON.stringify({ dataset_id: datasetId, target }) }),

  listRuns: () => request<{ runs: TrainingRun[] }>('/api/training/runs').then(r => r.runs),
  getRun: (id: string) => request<TrainingRun>(`/api/training/runs/${enc(id)}`),
  start: (data: StartTrainingRequest) => request<TrainingRun>('/api/training/runs', { method: 'POST', body: JSON.stringify(data) }),
  cancel: (id: string) => request<TrainingRun>(`/api/training/runs/${enc(id)}/cancel`, { method: 'POST' }),
  deleteRun: (id: string) => request<{ status: string }>(`/api/training/runs/${enc(id)}`, { method: 'DELETE' }),

  listLoras: (filter: { target?: string; model?: string } = {}) => {
    const query = new URLSearchParams()
    if (filter.target) query.set('target', filter.target)
    if (filter.model) query.set('model', filter.model)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request<{ loras: LoraEntry[] }>(`/api/training/loras${suffix}`).then(r => r.loras)
  },
  importLora: (data: { path: string; name?: string; target: string; trigger?: string }) =>
    request<LoraEntry>('/api/training/loras/import', { method: 'POST', body: JSON.stringify(data) }),
  /** Start a background download of a LoRA from a Hugging Face / Civitai / direct link.
   *  The optional api_key is sent once for the fetch and never stored anywhere. */
  downloadLora: (data: { url: string; target: string; name?: string; trigger?: string; api_key?: string }) =>
    request<{ job_id: string }>('/api/training/loras/download', { method: 'POST', body: JSON.stringify(data) }),
  updateLora: (id: string, data: { name?: string; trigger?: string; default_multiplier?: number }) =>
    request<LoraEntry>(`/api/training/loras/${enc(id)}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteLora: (id: string) => request<{ status: string }>(`/api/training/loras/${enc(id)}`, { method: 'DELETE' }),
}

/** Authenticated URL for a dataset image. */
export async function datasetMediaUrl(datasetId: string, file: string): Promise<string> {
  const standalone = mediaResolver()
  if (standalone) return standalone.output(file)
  const { url, token } = await getBackendCredentials()
  return `${url}/api/training/datasets/${enc(datasetId)}/media?path=${enc(file)}&token=${enc(token)}`
}
