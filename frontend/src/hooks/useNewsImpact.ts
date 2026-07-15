import { useMutation } from '@tanstack/react-query'
import type { NewsImpactRequest, NewsImpactResponse } from '../types'

async function fetchNewsImpact(req: NewsImpactRequest): Promise<NewsImpactResponse> {
  const res = await fetch('/api/news-impact', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(err.detail || '请求失败')
  }
  return res.json()
}

export function useNewsImpact() {
  return useMutation<NewsImpactResponse, Error, NewsImpactRequest>({
    mutationFn: fetchNewsImpact,
  })
}
