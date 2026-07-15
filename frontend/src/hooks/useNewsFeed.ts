import { useQuery } from '@tanstack/react-query'
import type { NewsFeedResponse } from '../types'

async function fetchNewsFeed(refresh = false): Promise<NewsFeedResponse> {
  const res = await fetch(`/api/news-feed${refresh ? '?refresh=true' : ''}`)
  if (!res.ok) throw new Error('获取新闻推送失败')
  return res.json()
}

export function useNewsFeed() {
  const query = useQuery<NewsFeedResponse, Error>({
    queryKey: ['news-feed'],
    queryFn: () => fetchNewsFeed(false),
    staleTime: 25 * 60 * 1000,   // 25分钟内不重新请求
    refetchOnWindowFocus: false,
  })

  const refresh = () => {
    query.refetch()
    fetch('/api/news-feed?refresh=true').catch(() => {})
  }

  return { ...query, refresh }
}
