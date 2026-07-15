/**
 * 除权除息提醒面板 — 持仓页顶部
 * - 静默检测持仓中所有待应用的除权除息事件
 * - 用户可选择对每只股票"应用"或"跳过"
 */
import { useEffect, useState, useCallback } from 'react'

interface EventDetail {
  ex_date: string
  description: string
  qty_before: number
  qty_after: number
  cost_before: number
  cost_after: number
  cash_received: number
}

interface PendingItem {
  symbol: string
  name: string
  buy_date: string
  events: EventDetail[]
  final_qty: number
  final_cost: number
}

interface Props {
  onApplied: () => void
}

export default function DividendAdjustPanel({ onApplied }: Props) {
  const [pending, setPending] = useState<PendingItem[]>([])
  const [expanded, setExpanded] = useState(false)
  const [applying, setApplying] = useState<string>('')   // 正在应用的symbol

  const refresh = useCallback(async () => {
    try {
      const r = await fetch('/api/portfolio/pending-adjustments')
      const d = await r.json()
      setPending(d.pending ?? [])
    } catch {}
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  if (pending.length === 0) return null

  const totalEvents = pending.reduce((s, p) => s + p.events.length, 0)

  const apply = async (symbol: string) => {
    setApplying(symbol)
    try {
      await fetch('/api/portfolio/apply-adjustments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: [symbol] }),
      })
      await refresh()
      onApplied()
    } finally {
      setApplying('')
    }
  }

  const skip = async (symbol: string) => {
    setApplying(symbol)
    try {
      await fetch('/api/portfolio/skip-adjustments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: [symbol] }),
      })
      await refresh()
    } finally {
      setApplying('')
    }
  }

  return (
    <div className="bg-gradient-to-r from-orange-950/60 to-amber-950/60 border border-orange-800/60 rounded-2xl overflow-hidden">
      {/* 折叠头 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between gap-3 hover:bg-orange-900/20 transition-colors"
      >
        <div className="flex items-center gap-3 text-left">
          <span className="text-xl">🔔</span>
          <div>
            <p className="text-sm font-semibold text-orange-200">
              发现 {totalEvents} 项除权除息事件待应用
            </p>
            <p className="text-[11px] text-orange-400/80 mt-0.5">
              涉及 {pending.length} 只股票 · 点击查看详情并确认是否应用
            </p>
          </div>
        </div>
        <span className="text-orange-400 text-sm shrink-0">
          {expanded ? '收起 ↑' : '查看详情 ↓'}
        </span>
      </button>

      {/* 详情面板 */}
      {expanded && (
        <div className="border-t border-orange-800/40 bg-gray-950/40 p-4 space-y-3">
          {pending.map(p => (
            <div key={p.symbol} className="bg-gray-900/80 border border-gray-800 rounded-xl p-4 space-y-3">
              {/* 股票头 */}
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-bold text-white">{p.name}</span>
                  <span className="text-xs text-gray-500 font-mono">{p.symbol}</span>
                  <span className="text-[10px] text-gray-600">买入: {p.buy_date}</span>
                </div>
              </div>

              {/* 事件列表 */}
              <div className="space-y-2">
                {p.events.map((e, i) => (
                  <div key={i} className="bg-gray-800/40 rounded-lg px-3 py-2 text-xs">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-amber-300 font-medium">
                        {e.ex_date}  {e.description}
                      </span>
                      {e.cash_received > 0 && (
                        <span className="text-green-400">
                          收现金 ¥{e.cash_received.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-gray-400">
                      <div>
                        <span className="text-gray-600">持股数：</span>
                        <span className="text-gray-300">{e.qty_before}</span>
                        {e.qty_before !== e.qty_after && (
                          <>
                            <span className="text-orange-400 mx-1">→</span>
                            <span className="text-white font-semibold">{e.qty_after}</span>
                          </>
                        )}
                      </div>
                      <div>
                        <span className="text-gray-600">成本价：</span>
                        <span className="text-gray-300">¥{e.cost_before.toFixed(3)}</span>
                        {e.cost_before !== e.cost_after && (
                          <>
                            <span className="text-orange-400 mx-1">→</span>
                            <span className="text-white font-semibold">¥{e.cost_after.toFixed(3)}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* 最终结果 */}
              {p.events.length > 1 && (
                <div className="bg-amber-950/30 border border-amber-800/40 rounded-lg px-3 py-2 text-xs">
                  <span className="text-amber-300 font-medium">最终：</span>
                  <span className="text-white">{p.final_qty}股</span>
                  <span className="text-gray-500 mx-1">·</span>
                  <span className="text-white">成本 ¥{p.final_cost.toFixed(3)}</span>
                </div>
              )}

              {/* 操作按钮 */}
              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => apply(p.symbol)}
                  disabled={applying === p.symbol}
                  className="flex-1 py-2 bg-orange-600 hover:bg-orange-500 disabled:opacity-40 text-white text-xs font-semibold rounded-lg transition-colors"
                >
                  {applying === p.symbol ? '应用中…' : '✅ 应用此调整'}
                </button>
                <button
                  onClick={() => skip(p.symbol)}
                  disabled={applying === p.symbol}
                  className="flex-1 py-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-gray-400 text-xs rounded-lg transition-colors"
                  title="如果你的券商成本价没变(说明实际买入日在除权除息之后)，点这里"
                >
                  ❌ 跳过(我的成本未变)
                </button>
              </div>
            </div>
          ))}

          {/* 底部提示 */}
          <p className="text-[10px] text-gray-600 text-center pt-1">
            💡 跳过的事件不会再次提醒。如果不确定，对照券商成本价：未变就跳过，已变就应用。
          </p>
        </div>
      )}
    </div>
  )
}
