/**
 * 脑库匹配面板 — 复盘页/研究页自动调用
 * 根据当前股票情况，从交易脑库匹配最相关的规则
 */
import { useEffect, useState } from 'react'

interface MatchedRule {
  id: string
  category: string
  rule: string
  conditions: string[]
  confidence: number
  relevance: number
  reason: string
  validated_win: number
  validated_loss: number
  created_at?: string       // 入库时间（ISO）
  event_date?: string       // 关联政策/消息的发布时间
  effective_date?: string   // 落地/生效时间
}

// ISO / 各种日期串 → 紧凑显示（取 YYYY-MM-DD 的月日，或原样短串）
function shortDate(s?: string): string {
  if (!s) return ''
  const m = s.match(/(\d{4})-(\d{2})-(\d{2})/)
  if (m) return `${m[2]}/${m[3]}`
  const ym = s.match(/(\d{4})-(\d{2})/)
  if (ym) return `${ym[1]}/${ym[2]}`
  return s.length > 10 ? s.slice(0, 10) : s
}

const CATEGORIES: Record<string, { label: string; color: string }> = {
  entry:      { label: '买入信号', color: 'text-green-400' },
  exit:       { label: '卖出信号', color: 'text-red-400' },
  risk:       { label: '风险控制', color: 'text-orange-400' },
  sector:     { label: '板块逻辑', color: 'text-blue-400' },
  macro:      { label: '宏观判断', color: 'text-purple-400' },
  psychology: { label: '心理纪律', color: 'text-yellow-400' },
  pattern:    { label: '技术形态', color: 'text-cyan-400' },
  other:      { label: '其他',     color: 'text-gray-400' },
}

export default function BrainMatchPanel({ context }: { context: string }) {
  const [matches, setMatches] = useState<MatchedRule[]>([])
  const [state, setState] = useState<'idle' | 'loading' | 'done' | 'empty' | 'no-brain' | 'error'>('idle')

  useEffect(() => {
    if (!context) return
    setState('loading')
    let cancelled = false

    ;(async () => {
      try {
        // 先看脑库有没有规则
        const stats = await fetch('/api/brain/stats').then(r => r.json())
        if (cancelled) return
        if (!stats.total_rules) {
          setState('no-brain')
          return
        }

        const r = await fetch('/api/brain/match', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ context }),
        })
        if (cancelled) return
        const d = await r.json()
        const ms: MatchedRule[] = d.matches ?? []
        setMatches(ms)
        setState(ms.length ? 'done' : 'empty')
      } catch {
        if (!cancelled) setState('error')
      }
    })()

    return () => { cancelled = true }
  }, [context])

  // 无规则时不展示，节省空间
  if (state === 'no-brain' || state === 'idle') return null

  return (
    <div className="bg-gradient-to-br from-purple-950/40 to-blue-950/40 border border-purple-800/40 rounded-xl p-5">
      <h3 className="text-sm font-medium text-purple-300 mb-3 flex items-center gap-2">
        <span>🧠 脑库匹配</span>
        <span className="text-[10px] text-gray-500 font-normal">从你的交易系统中调取相关规则</span>
      </h3>

      {state === 'loading' && (
        <div className="text-xs text-gray-500 flex items-center gap-2 py-2">
          <div className="w-3 h-3 border border-purple-500 border-t-transparent rounded-full animate-spin" />
          AI 正在匹配脑库规则…
        </div>
      )}

      {state === 'empty' && (
        <p className="text-xs text-gray-500 py-2">脑库中暂无与该股票相关的规则</p>
      )}

      {state === 'error' && (
        <p className="text-xs text-red-400 py-2">匹配失败</p>
      )}

      {state === 'done' && (
        <div className="space-y-3">
          {matches.map((m, i) => {
            const cat = CATEGORIES[m.category] ?? CATEGORIES.other
            const totalValidated = (m.validated_win ?? 0) + (m.validated_loss ?? 0)
            return (
              <div key={m.id} className="bg-gray-900/60 border border-gray-800 rounded-lg p-3 space-y-2">
                <div className="flex items-start gap-2">
                  <span className="text-xs text-purple-400 font-mono shrink-0">#{i+1}</span>
                  <span className={`text-[10px] font-semibold ${cat.color} shrink-0`}>{cat.label}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white leading-relaxed">{m.rule}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-[10px] text-purple-400 font-mono">相关 {Math.round(m.relevance * 100)}%</div>
                    <div className="text-[10px] text-gray-600">置信 {Math.round(m.confidence * 100)}%</div>
                  </div>
                </div>
                {/* 政策/消息时间线 + 入库时间 */}
                {(m.event_date || m.effective_date || m.created_at) && (
                  <div className="flex items-center gap-2 pl-8 flex-wrap text-[10px]">
                    {m.event_date && (
                      <span className="text-blue-300/80 bg-blue-950/40 px-1.5 py-0.5 rounded">
                        📅 发布 {shortDate(m.event_date)}
                      </span>
                    )}
                    {m.effective_date && (
                      <span className="text-emerald-300/80 bg-emerald-950/40 px-1.5 py-0.5 rounded">
                        🟢 落地 {shortDate(m.effective_date)}
                      </span>
                    )}
                    {m.created_at && (
                      <span className="text-gray-600" title="该规则进入脑库的时间">
                        录入 {shortDate(m.created_at)}
                      </span>
                    )}
                  </div>
                )}
                {m.reason && (
                  <p className="text-[11px] text-gray-500 pl-8 border-l-2 border-purple-900/50">
                    💡 {m.reason}
                  </p>
                )}
                {(m.conditions.length > 0 || totalValidated > 0) && (
                  <div className="flex items-center gap-2 pl-8 flex-wrap">
                    {m.conditions.map((c, j) => (
                      <span key={j} className="text-[9px] text-gray-500 bg-gray-800/60 px-1.5 py-0.5 rounded-full">
                        {c}
                      </span>
                    ))}
                    {totalValidated > 0 && (
                      <span className="text-[9px] text-gray-600">
                        实战 <span className="text-green-500">{m.validated_win}✓</span> <span className="text-red-500">{m.validated_loss}✗</span>
                      </span>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
