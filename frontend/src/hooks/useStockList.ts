import { useQuery } from '@tanstack/react-query'

export interface StockItem {
  symbol: string
  name: string
  market: string
  pinyin?: string   // 股票名称拼音首字母缩写，如 北方华创 → bfhc
}

async function fetchStockList(): Promise<StockItem[]> {
  const res = await fetch('/api/stocks/list')
  if (!res.ok) throw new Error('获取股票列表失败')
  const data = await res.json()
  return data.stocks as StockItem[]
}

export function useStockList() {
  return useQuery<StockItem[], Error>({
    queryKey: ['stock-list'],
    queryFn: fetchStockList,
    staleTime: 24 * 60 * 60 * 1000,   // 24小时不重新请求
    gcTime:    24 * 60 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  })
}
