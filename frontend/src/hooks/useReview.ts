import { useState, useCallback } from 'react'
import { reviewStore, useReviewEntry, type ReviewParams } from '../stores/reviewStore'

/**
 * 复盘 hook —— 仅是 reviewStore 的薄订阅层。
 * 真正的请求/流式/缓存都在 reviewStore（模块级），所以：
 *   - 切到别的功能不会打断生成
 *   - 已生成过的股票再选中 → 秒显缓存，不重复生成
 */
export function useReview() {
  const [currentKey, setCurrentKey] = useState<string | null>(null)
  const entry = useReviewEntry(currentKey)

  const mutate = useCallback((params: ReviewParams, displayName?: string) => {
    const key = reviewStore.makeKey(params)
    setCurrentKey(key)
    // 不 await：让它在后台跑，组件通过订阅拿进度/结果
    void reviewStore.run(params, displayName)
  }, [])

  return {
    mutate,
    data:           entry?.data,
    streamedReport: entry?.report ?? '',
    isPending:      entry?.isPending ?? false,
    isStreaming:    entry?.isStreaming ?? false,
    error:          entry?.error ? new Error(entry.error) : null,
  }
}
