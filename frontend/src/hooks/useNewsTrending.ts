import { useQuery } from '@tanstack/react-query'

export type TrendingItem = {
  rank: number
  title: string
  title_en?: string
  summary: string
  url: string
  published: string
  one_line: string
  direction: 'positive' | 'negative' | 'neutral'
  stocks: string[]
  sources: string[]
  source_count: number
  hotness: number
  cluster_size: number
}

export type TrendingResponse = {
  market: 'cn' | 'intl'
  items: TrendingItem[]
  raw_count: number
  updated_at: number
}

async function fetchTrending(market: 'cn' | 'intl', refresh = false): Promise<TrendingResponse> {
  const u = `/api/news-trending?market=${market}&top=12${refresh ? '&refresh=true' : ''}`
  const res = await fetch(u)
  if (!res.ok) throw new Error('热搜榜拉取失败')
  return res.json()
}

export function useNewsTrending(market: 'cn' | 'intl') {
  const query = useQuery<TrendingResponse, Error>({
    queryKey: ['news-trending', market],
    queryFn: () => fetchTrending(market, false),
    staleTime: market === 'cn' ? 4 * 60 * 1000 : 25 * 60 * 1000,
    refetchOnWindowFocus: false,
  })
  const refresh = () => {
    query.refetch()
    fetch(`/api/news-trending?market=${market}&refresh=true`).catch(() => {})
  }
  return { ...query, refresh }
}
