import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Gauge } from 'lucide-react'

interface Evaluation {
  ready?: boolean
  snapshot_count?: number
  verdict?: string
  sector_hit_rate?: number
  event_count?: number
  market?: {
    first_action?: string
    last_action?: string
    first_score?: number
    last_score?: number
    consistent?: boolean
    summary?: string
  }
  sectors?: { name: string; initial_score: number; final_score: number; followed: boolean; summary: string }[]
  lessons?: string[]
  capture_status?: {
    enabled?: boolean
    state?: string
    snapshot_count?: number
    first_at?: string
    last_at?: string
    next_session?: string
  }
}

export default function MarketRadarEvaluation({ tradeDate }: { tradeDate: string }) {
  const [data, setData] = useState<Evaluation | null>(null)

  useEffect(() => {
    let active = true
    fetch(`/api/market-radar/evaluation?trade_date=${tradeDate}`)
      .then(response => response.ok ? response.json() : null)
      .then(payload => { if (active) setData(payload) })
      .catch(() => { if (active) setData(null) })
    return () => { active = false }
  }, [tradeDate])

  if (!data) return null
  if (!data.ready) {
    const capture = data.capture_status
    return (
      <section className="rounded border border-gray-800 bg-gray-900/50 px-4 py-3">
        <div className="flex items-start gap-3">
          <Gauge className="mt-0.5 h-4 w-4 shrink-0 text-blue-400" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-white">自动采集状态</h2>
              <span className="rounded border border-blue-500/30 bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-300">已启用 · 每3分钟</span>
            </div>
            <p className="mt-1 text-xs leading-5 text-gray-400">{data.verdict}</p>
            <p className="mt-1 text-xs leading-5 text-gray-600">{capture?.next_session || '达到两个不同时点后，系统会自动开始检验判断延续性。'}</p>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
      <div className="flex flex-col gap-1 border-b border-gray-800 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2"><Gauge className="h-4 w-4 text-blue-400" /><h2 className="text-sm font-semibold text-white">系统判断复核</h2></div>
        <p className="text-xs text-gray-500">{data.snapshot_count} 个盘中快照 · {data.event_count || 0} 次关键变化</p>
      </div>
      <div className="grid gap-px bg-gray-800 md:grid-cols-3">
        <div className="bg-gray-900 px-4 py-3"><div className="text-xs text-gray-500">最终评价</div><div className="mt-1 text-sm font-semibold text-white">{data.verdict}</div></div>
        <div className="bg-gray-900 px-4 py-3"><div className="text-xs text-gray-500">市场方向</div><div className={`mt-1 text-sm font-semibold ${data.market?.consistent ? 'text-red-300' : 'text-amber-300'}`}>{data.market?.first_action} → {data.market?.last_action}</div><div className="mt-1 text-xs text-gray-600">评分 {data.market?.first_score} → {data.market?.last_score}</div></div>
        <div className="bg-gray-900 px-4 py-3"><div className="text-xs text-gray-500">强板块延续率</div><div className="mt-1 text-lg font-semibold text-blue-300">{data.sector_hit_rate || 0}%</div></div>
      </div>
      <div className="divide-y divide-gray-800">
        {(data.sectors || []).slice(0, 5).map(row => (
          <div key={row.name} className="grid gap-2 px-4 py-2.5 text-sm sm:grid-cols-[1fr_120px_1fr] sm:items-center">
            <div className="flex items-center gap-2">{row.followed ? <CheckCircle2 className="h-4 w-4 text-red-400" /> : <AlertTriangle className="h-4 w-4 text-amber-400" />}<span className="text-gray-200">{row.name}</span></div>
            <div className="text-gray-500">{row.initial_score} → {row.final_score}分</div>
            <div className={row.followed ? 'text-red-300' : 'text-amber-300'}>{row.summary}</div>
          </div>
        ))}
      </div>
      {!!data.lessons?.length && <div className="border-t border-gray-800 px-4 py-3 text-xs leading-5 text-gray-500">{data.lessons.join(' ')}</div>}
    </section>
  )
}
