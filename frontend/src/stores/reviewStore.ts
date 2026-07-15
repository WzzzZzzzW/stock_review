/**
 * 复盘结果 store —— 按「股票+区间」缓存，跨页面共享
 *
 * 解决两个痛点：
 *   1. 生成中切到别的功能不会被打断（fetch/SSE 跑在 store 里，不随组件卸载而取消）
 *   2. 已经生成过的股票再切回来 / 重新选中 → 秒显缓存，不重复生成
 *
 * 同时把每次生成登记到 taskCenter，顶栏指示器可见、可并发。
 */
import { useSyncExternalStore } from 'react'
import type { ReviewResponse } from '../types'
import { taskCenter } from './taskCenter'

export interface ReviewParams {
  symbol: string
  start?: string
  end?: string
}

export interface ReviewEntry {
  key: string
  params: ReviewParams
  name: string
  data?: ReviewResponse
  report: string        // 流式累积 / 最终报告
  isPending: boolean    // 阶段一：采集结构化数据中
  isStreaming: boolean  // 阶段二：AI 报告流式中
  error?: string
}

function makeKey(p: ReviewParams): string {
  return `${p.symbol}|${p.start ?? ''}|${p.end ?? ''}`
}

const entries = new Map<string, ReviewEntry>()
const listeners = new Set<() => void>()
let version = 0

function emit() {
  version++
  listeners.forEach(l => l())
}

function isComplete(e: ReviewEntry | undefined): boolean {
  return !!e && !e.isPending && !e.isStreaming && !e.error && !!e.data
}

async function run(params: ReviewParams, displayName?: string): Promise<string> {
  const key = makeKey(params)
  const existing = entries.get(key)

  // 已完成且无错误 → 秒显，不重复生成
  if (isComplete(existing)) return key
  // 正在跑 → 不重复触发（切回来会自动订阅到同一条目的进度）
  if (existing && (existing.isPending || existing.isStreaming)) return key

  const entry: ReviewEntry = {
    key, params,
    name: displayName || params.symbol,
    report: '', isPending: true, isStreaming: false,
  }
  entries.set(key, entry)
  emit()

  const taskId = `review:${key}`
  taskCenter.start(taskId, 'review', `复盘·${entry.name}`, { symbol: params.symbol, name: entry.name })
  taskCenter.update(taskId, '采集数据中…')

  try {
    // 阶段一：结构化数据（无 AI，较快）
    const res = await fetch('/api/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error((err as { detail?: string }).detail || '请求失败')
    }
    const reviewData: ReviewResponse & { cache_key?: string } = await res.json()
    entry.data = reviewData
    entry.name = reviewData.name || entry.name
    entry.isPending = false
    emit()
    // 阶段一拿到真实股票名后，刷新任务标签（不重置计时）
    taskCenter.setLabel(taskId, `复盘·${entry.name}`, { symbol: params.symbol, name: entry.name })
    taskCenter.update(taskId, 'AI 报告生成中…')

    // 阶段二：SSE 流式 AI 报告
    const cacheKey = reviewData.cache_key
    if (!cacheKey) {
      taskCenter.finish(taskId)
      return key
    }

    entry.isStreaming = true
    emit()

    const streamRes = await fetch(
      `/api/review/stream-report?cache_key=${encodeURIComponent(cacheKey)}`,
    )
    if (!streamRes.ok || !streamRes.body) {
      entry.isStreaming = false
      emit()
      taskCenter.finish(taskId)
      return key
    }

    const reader = streamRes.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let reportText = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        if (!raw) continue
        let chunk: string
        try { chunk = JSON.parse(raw) } catch { chunk = raw }
        if (chunk === '[DONE]') {
          entry.isStreaming = false
          emit()
          taskCenter.finish(taskId)
          return key
        }
        reportText += chunk
        entry.report = reportText
        emit()
      }
    }
    entry.isStreaming = false
    emit()
    taskCenter.finish(taskId)
    return key
  } catch (e: unknown) {
    entry.isPending = false
    entry.isStreaming = false
    entry.error = e instanceof Error ? e.message : String(e)
    emit()
    taskCenter.fail(taskId, entry.error)
    return key
  }
}

export const reviewStore = {
  run,
  makeKey,
  subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l) } },
  getVersion() { return version },
}

/** 订阅某个 key 对应的复盘条目；store 任意变化都会触发重渲染并重新读取。 */
export function useReviewEntry(key: string | null): ReviewEntry | undefined {
  useSyncExternalStore(reviewStore.subscribe, reviewStore.getVersion, reviewStore.getVersion)
  return key ? entries.get(key) : undefined
}
