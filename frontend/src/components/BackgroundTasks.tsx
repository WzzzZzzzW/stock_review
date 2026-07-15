/**
 * 后台任务指示器 —— 挂在顶栏，显示正在生成 / 最近完成的任务。
 * 解决用户痛点：「生成要等 5~10 秒，不敢切走」。现在可以放心切走，
 * 这里能看到它在后台继续跑，跑完点一下就回到结果（已缓存，秒显）。
 */
import { useState } from 'react'
import { useTasks, taskCenter, type BgTask } from '../stores/taskCenter'

interface Props {
  onOpenReview?: (symbol: string, name: string) => void
}

function statusDot(t: BgTask) {
  if (t.status === 'running') return <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse shrink-0" />
  if (t.status === 'error')   return <span className="w-2 h-2 rounded-full bg-red-500 shrink-0" />
  return <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
}

export default function BackgroundTasks({ onOpenReview }: Props) {
  const tasks = useTasks()
  const [open, setOpen] = useState(false)

  const running = tasks.filter(t => t.status === 'running')
  // 最近的在前
  const ordered = [...tasks].sort((a, b) => (b.endedAt ?? b.startedAt) - (a.endedAt ?? a.startedAt))

  if (tasks.length === 0) return null

  const openTask = (t: BgTask) => {
    if (t.kind === 'review' && onOpenReview && t.payload?.symbol) {
      onOpenReview(String(t.payload.symbol), String(t.payload.name ?? ''))
      setOpen(false)
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors ${
          running.length > 0
            ? 'bg-blue-600/20 text-blue-300 border border-blue-700/50'
            : 'text-gray-400 hover:text-white hover:bg-gray-800 border border-transparent'
        }`}
        title="后台任务"
      >
        {running.length > 0 ? (
          <>
            <span className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <span>{running.length} 个生成中</span>
          </>
        ) : (
          <>
            <span>🗂️</span>
            <span className="hidden sm:inline">后台任务</span>
          </>
        )}
      </button>

      {open && (
        <>
          {/* 点击外部关闭 */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-2 w-80 max-h-96 overflow-y-auto z-50 bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl p-2">
            <div className="flex items-center justify-between px-2 py-1.5">
              <span className="text-xs font-semibold text-gray-300">后台任务</span>
              {ordered.some(t => t.status !== 'running') && (
                <button
                  onClick={() => taskCenter.clearFinished()}
                  className="text-[10px] text-gray-500 hover:text-white"
                >清除已完成</button>
              )}
            </div>
            <div className="space-y-1">
              {ordered.map(t => {
                const clickable = t.kind === 'review' && !!t.payload?.symbol
                return (
                  <div
                    key={t.id}
                    onClick={() => openTask(t)}
                    className={`flex items-start gap-2 px-2.5 py-2 rounded-xl ${
                      clickable ? 'cursor-pointer hover:bg-gray-800' : ''
                    }`}
                  >
                    <div className="mt-1">{statusDot(t)}</div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-white truncate">{t.label}</div>
                      <div className="text-[10px] text-gray-500 truncate">
                        {t.status === 'running' && (t.progress || '处理中…')}
                        {t.status === 'done' && '已完成 · 点击查看'}
                        {t.status === 'error' && <span className="text-red-400">失败：{t.error}</span>}
                      </div>
                    </div>
                    <button
                      onClick={e => { e.stopPropagation(); taskCenter.remove(t.id) }}
                      className="text-gray-700 hover:text-red-400 text-xs shrink-0"
                      title="移除"
                    >✕</button>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
