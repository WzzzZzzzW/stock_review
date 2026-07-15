import { useQuery } from '@tanstack/react-query'
import type { NewsFeedResponse } from '../types'

async function fetchNewsFeedCn(refresh = false): Promise<NewsFeedResponse> {
  const res = await fetch(`/api/news-feed-cn${refresh ? '?refresh=true' : ''}`)
  if (!res.ok) throw new Error('获取中文新闻推送失败')
  return res.json()
}

export function useNewsFeedCn() {
  const query = useQuery<NewsFeedResponse, Error>({
    queryKey: ['news-feed-cn'],
    queryFn: () => fetchNewsFeedCn(false),
    staleTime: 12 * 60 * 1000,   // 12分钟
    refetchOnWindowFocus: false,
  })

  const refresh = () => {
    query.refetch()
    fetch('/api/news-feed-cn?refresh=true').catch(() => {})
  }

  return { ...query, refresh }
}
