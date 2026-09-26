import { useCallback, useEffect, useRef, useState } from 'react'
import { jobsApi, subscribeJobs, type JobListQuery } from '../../lib/jobs-api'
import { logger } from '../../lib/logger'
import type { Job } from '../../types/jobs'

export interface JobsState {
  jobs: Job[]
  loading: boolean
  error: string
  nextCursor: string
  feedMode: 'sse' | 'poll' | 'connecting'
  refresh: () => Promise<void>
  loadMore: () => Promise<void>
}

function mergeJob(list: Job[], job: Job): Job[] {
  const index = list.findIndex(j => j.id === job.id)
  if (index === -1) return [job, ...list].sort((a, b) => b.created_at - a.created_at || (a.id < b.id ? 1 : -1))
  const next = list.slice()
  next[index] = job
  return next
}

function matches(job: Job, query: JobListQuery): boolean {
  if (query.kind && job.kind !== query.kind) return false
  if (query.status === 'active') {
    if (job.status !== 'queued' && job.status !== 'running') return false
  } else if (query.status && job.status !== query.status) return false
  if (query.project && job.project_id !== query.project) return false
  if (query.q) {
    const needle = query.q.toLowerCase()
    if (!`${job.prompt} ${job.title} ${job.model}`.toLowerCase().includes(needle)) return false
  }
  return true
}

/** A live, filtered job list: the initial page from the API, then feed updates merged in place. */
export function useJobs(query: JobListQuery): JobsState {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [nextCursor, setNextCursor] = useState('')
  const [feedMode, setFeedMode] = useState<'sse' | 'poll' | 'connecting'>('connecting')
  const queryRef = useRef(query)
  queryRef.current = query
  const key = JSON.stringify(query)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const { jobs: page, next_cursor } = await jobsApi.list({ ...queryRef.current, limit: queryRef.current.limit ?? 60 })
      setJobs(page)
      setNextCursor(next_cursor)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (!nextCursor) return
    try {
      const { jobs: page, next_cursor } = await jobsApi.list({ ...queryRef.current, cursor: nextCursor, limit: 60 })
      setJobs(prev => {
        const seen = new Set(prev.map(j => j.id))
        return [...prev, ...page.filter(j => !seen.has(j.id))]
      })
      setNextCursor(next_cursor)
    } catch (err) {
      logger.warn(`Could not load more jobs: ${err}`)
    }
  }, [nextCursor])

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, refresh])

  useEffect(() => {
    const handle = subscribeJobs(event => {
      if (event.type === 'reset') {
        void refresh()
      } else if (event.type === 'deleted') {
        setJobs(prev => prev.filter(j => j.id !== event.id))
      } else if (matches(event.job, queryRef.current)) {
        setJobs(prev => mergeJob(prev, event.job))
      } else {
        setJobs(prev => prev.filter(j => j.id !== event.job.id))
      }
    }, setFeedMode)
    return () => handle.close()
  }, [refresh])

  return { jobs, loading, error, nextCursor, feedMode, refresh, loadMore }
}
