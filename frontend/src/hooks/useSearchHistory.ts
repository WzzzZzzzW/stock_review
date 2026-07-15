/**
 * 股票搜索历史记录 hook
 * 持久化存储在 localStorage，最多保留 20 条，按时间倒序
 */
import { useState, useCallback } from 'react'

const STORAGE_KEY = 'stock_search_history_v1'
const MAX_ENTRIES = 20

export interface SearchHistoryItem {
  symbol: string
  name: string
  timestamp: number
}

function readHistory(): SearchHistoryItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeHistory(items: SearchHistoryItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
  } catch {
    // storage full or unavailable — silent fail
  }
}

export function useSearchHistory() {
  const [history, setHistory] = useState<SearchHistoryItem[]>(() => readHistory())

  const addToHistory = useCallback((symbol: string, name: string) => {
    setHistory(prev => {
      // 去重（同 symbol 先移除）
      const filtered = prev.filter(h => h.symbol !== symbol)
      const next = [{ symbol, name, timestamp: Date.now() }, ...filtered].slice(0, MAX_ENTRIES)
      writeHistory(next)
      return next
    })
  }, [])

  const removeFromHistory = useCallback((symbol: string) => {
    setHistory(prev => {
      const next = prev.filter(h => h.symbol !== symbol)
      writeHistory(next)
      return next
    })
  }, [])

  const clearHistory = useCallback(() => {
    writeHistory([])
    setHistory([])
  }, [])

  return { history, addToHistory, removeFromHistory, clearHistory }
}
