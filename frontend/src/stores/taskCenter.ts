/**
 * 全局后台任务中心 —— 模块级外部 store
 *
 * 任何「耗时生成」（复盘、AI 报告等）都可以在这里登记成一个后台任务：
 *   - 切到别的功能不会打断它（任务跑在 store 里，不依赖某个组件挂载）
 *   - 顶栏指示器能看到哪些任务在跑 / 进度 / 已完成
 *   - 多个任务可并发排队
 *
 * 用 useSyncExternalStore 暴露给组件，也可被普通函数（如 reviewStore）直接调用。
 */
import { useSyncExternalStore } from 'react'

export type TaskStatus = 'running' | 'done' | 'error'

export interface BgTask {
  id: string
  kind: string                       // 'review' | 'office' | ...
  label: string                      // 显示名，如 "复盘·中远海控"
  status: TaskStatus
  progress: string
  error?: string
  startedAt: number
  endedAt?: number
  payload?: Record<string, unknown>  // 供指示器点击跳转用，如 { symbol, name }
}

let tasks: BgTask[] = []
const listeners = new Set<() => void>()

function emit() {
  // 新数组引用 → useSyncExternalStore 才能感知变化
  tasks = [...tasks]
  listeners.forEach(l => l())
}

export const taskCenter = {
  start(id: string, kind: string, label: string, payload?: Record<string, unknown>) {
    const existing = tasks.find(t => t.id === id)
    if (existing) {
      Object.assign(existing, {
        kind, label, status: 'running' as TaskStatus,
        progress: '', error: undefined,
        startedAt: Date.now(), endedAt: undefined,
        payload: payload ?? existing.payload,
      })
    } else {
      tasks.push({ id, kind, label, status: 'running', progress: '', startedAt: Date.now(), payload })
    }
    emit()
  },
  update(id: string, progress: string) {
    const t = tasks.find(t => t.id === id)
    if (t) { t.progress = progress; emit() }
  },
  setLabel(id: string, label: string, payload?: Record<string, unknown>) {
    const t = tasks.find(t => t.id === id)
    if (t) { t.label = label; if (payload) t.payload = payload; emit() }
  },
  finish(id: string) {
    const t = tasks.find(t => t.id === id)
    if (t) { t.status = 'done'; t.endedAt = Date.now(); emit() }
  },
  fail(id: string, error: string) {
    const t = tasks.find(t => t.id === id)
    if (t) { t.status = 'error'; t.error = error; t.endedAt = Date.now(); emit() }
  },
  remove(id: string) {
    tasks = tasks.filter(t => t.id !== id)
    emit()
  },
  clearFinished() {
    tasks = tasks.filter(t => t.status === 'running')
    emit()
  },
  getAll() { return tasks },
  subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l) } },
}

export function useTasks(): BgTask[] {
  return useSyncExternalStore(taskCenter.subscribe, taskCenter.getAll, taskCenter.getAll)
}
