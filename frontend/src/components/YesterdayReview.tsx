import { useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * 昨日复盘（单日聚焦）—— 只看最近一个交易日「这只票发生了什么」。
 * 自带 fetch + SSE，懒触发（点按钮才请求），与 90 天区间复盘相互独立。
 * A股惯例：红涨绿跌。
 */

interface Daily {
  date: string
  open?: number; high?: number; low?: number; close?: number; prev_close?: number
  pct_change?: number; amplitude?: number
  volume?: number; avg_vol20?: number; vol_ratio?: number; turn?: number
  ma5?: number; ma20?: number; ma60?: number; price_vs_ma?: string; rsi?: number
  is_up_limit?: boolean; is_dn_limit?: boolean; limit_pct?: number
}
interface FundFlow {
  main_net?: number; main_net_pct?: number
  super_net?: number; big_net?: number; mid_net?: number; small_net?: number
}
interface YdData {
  symbol: string; name: string
  daily: Daily
  lhb: any[]
  ths_hot: Record<string, string[]>
  industry_rank: { matched?: any }
  fund_flow: FundFlow
  news: { title: string; time: string; source?: string }[]
  announcements: { title: string; date: string; type?: string }[]
  cache_key?: string
}

const upDownCls = (v?: number) =>
  v == null ? 'text-gray-300' : v > 0 ? 'text-red-400' : v < 0 ? 'text-emerald-400' : 'text-gray-300'

const fmt = (v?: number, dec = 2) => (v == null || Number.isNaN(v) ? '--' : v.toFixed(dec))
const pctStr = (v?: number) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
const yi = (v?: number) => (v == null ? '--' : `${v >= 0 ? '+' : ''}${(v / 1e8).toFixed(2)}亿`)

function Stat({ label, value, cls = 'text-gray-200' }: { label: string; value: string; cls?: string }) {
  return (
    <div className="bg-gray-800/50 rounded-lg px-3 py-2">
      <div className="text-[10px] text-gray-500">{label}</div>
      <div className={`text-sm font-mono font-semibold ${cls}`}>{value}</div>
    </div>
  )
}

export default function YesterdayReview({ symbol, name }: { symbol: string; name?: string }) {
  const [open, setOpen]       = useState(false)
  const [data, setData]       = useState<YdData | null>(null)
  const [report, setReport]   = useState('')
  const [loading, setLoading] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [error, setError]     = useState('')

  const run = useCallback(async () => {
    setLoading(true); setError(''); setReport(''); setData(null)
    try {
      const res = await fetch('/api/review/yesterday', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }),
      })
      if (!res.ok) {
        const e = await res.json().catch(() => ({}))
        throw new Error((e as { detail?: string }).detail || '请求失败')
      }
      const yd: YdData = await res.json()
      setData(yd)
      setLoading(false)

      const ck = yd.cache_key
      if (!ck) return
      setStreaming(true)
      const sres = await fetch(`/api/review/yesterday/stream-report?cache_key=${encodeURIComponent(ck)}`)
      if (!sres.ok || !sres.body) { setStreaming(false); return }
      const reader = sres.body.getReader()
      const decoder = new TextDecoder()
      let buffer = '', text = ''
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
          if (chunk === '[DONE]') { setStreaming(false); return }
          text += chunk
          setReport(text)
        }
      }
      setStreaming(false)
    } catch (e) {
      setLoading(false); setStreaming(false)
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [symbol])

  const handleToggle = () => {
    const next = !open
    setOpen(next)
    if (next && !data && !loading) run()
  }

  const d = data?.daily
  const matched = data?.industry_rank?.matched
  const ff = data?.fund_flow

  return (
    <div className="bg-gray-900 border border-indigo-900/50 rounded-xl overflow-hidden">
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-gray-800/40 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-indigo-300">
          📅 昨日复盘
          <span className="text-xs text-gray-500 font-normal">只看最近一个交易日发生了什么</span>
        </span>
        <span className="flex items-center gap-2">
          {d && (
            <span className={`text-sm font-bold font-mono ${upDownCls(d.pct_change)}`}>
              {d.date} {pctStr(d.pct_change)}
            </span>
          )}
          <span className="text-xs text-gray-500">{open ? '收起 ▲' : '展开 ▼'}</span>
        </span>
      </button>

      {open && (
        <div className="px-5 pb-5 space-y-4 border-t border-gray-800 pt-4">
          {loading && (
            <div className="text-center py-6">
              <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
              <div className="text-xs text-gray-500">正在采集 {name || symbol} 昨日量价/资金/席位/题材…</div>
            </div>
          )}
          {error && (
            <div className="bg-red-900/30 border border-red-700 rounded-lg p-3 text-red-300 text-xs flex items-center justify-between">
              <span>{error}</span>
              <button onClick={run} className="text-red-200 underline ml-3 shrink-0">重试</button>
            </div>
          )}

          {d && (
            <>
              {/* 定性徽章 */}
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-lg font-bold text-white">{data!.name}</span>
                <span className="text-xs text-gray-500 font-mono">{data!.symbol}</span>
                <span className={`text-lg font-bold font-mono ${upDownCls(d.pct_change)}`}>{pctStr(d.pct_change)}</span>
                {d.is_up_limit && <span className="text-xs px-2 py-0.5 rounded bg-red-700 text-white font-bold">涨停 🚀</span>}
                {d.is_dn_limit && <span className="text-xs px-2 py-0.5 rounded bg-emerald-700 text-white font-bold">跌停 💀</span>}
                {!d.is_up_limit && !d.is_dn_limit && d.vol_ratio != null && d.vol_ratio >= 1.5 &&
                  <span className="text-xs px-2 py-0.5 rounded bg-amber-700/60 text-amber-200">放量</span>}
                {d.vol_ratio != null && d.vol_ratio <= 0.7 &&
                  <span className="text-xs px-2 py-0.5 rounded bg-gray-700 text-gray-300">缩量</span>}
              </div>

              {/* 量价网格 */}
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                <Stat label="开盘" value={fmt(d.open)} cls={upDownCls(d.open != null && d.prev_close != null ? d.open - d.prev_close : undefined)} />
                <Stat label="最高" value={fmt(d.high)} cls="text-red-400/80" />
                <Stat label="最低" value={fmt(d.low)} cls="text-emerald-400/80" />
                <Stat label="收盘" value={fmt(d.close)} cls={upDownCls(d.pct_change)} />
                <Stat label="振幅" value={d.amplitude != null ? `${fmt(d.amplitude)}%` : '--'} />
                <Stat label="量比(vs20日)" value={d.vol_ratio != null ? `${fmt(d.vol_ratio)}x` : '--'}
                  cls={d.vol_ratio != null && d.vol_ratio >= 1.5 ? 'text-red-400' : d.vol_ratio != null && d.vol_ratio <= 0.7 ? 'text-gray-500' : 'text-gray-200'} />
                <Stat label="换手率" value={d.turn != null ? `${fmt(d.turn)}%` : '--'} />
                <Stat label="成交量" value={d.volume != null ? `${(d.volume / 10000).toFixed(1)}万手` : '--'} />
              </div>
              <div className="text-[11px] text-gray-500 flex flex-wrap gap-x-4 gap-y-1">
                {d.price_vs_ma && <span>均线：{d.price_vs_ma}</span>}
                {d.rsi != null && <span>RSI(14)：{fmt(d.rsi, 1)}</span>}
                <span>MA5 {fmt(d.ma5)} · MA20 {fmt(d.ma20)} · MA60 {fmt(d.ma60)}</span>
              </div>

              {/* 资金流向 */}
              {ff && (ff.main_net != null) && (
                <div className="bg-gray-800/40 rounded-lg p-3">
                  <div className="text-[11px] text-gray-500 mb-1.5">💰 当日资金流向</div>
                  <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs font-mono">
                    <span>主力净流入 <b className={upDownCls(ff.main_net)}>{yi(ff.main_net)}</b>
                      {ff.main_net_pct != null && <span className="text-gray-500">（{fmt(ff.main_net_pct)}%）</span>}</span>
                    <span className="text-gray-400">超大单 <span className={upDownCls(ff.super_net)}>{yi(ff.super_net)}</span></span>
                    <span className="text-gray-400">大单 <span className={upDownCls(ff.big_net)}>{yi(ff.big_net)}</span></span>
                    <span className="text-gray-400">小单 <span className={upDownCls(ff.small_net)}>{yi(ff.small_net)}</span></span>
                  </div>
                </div>
              )}

              {/* 龙虎榜 */}
              {(data!.lhb ?? []).length > 0 && (
                <div className="bg-amber-900/15 border border-amber-900/40 rounded-lg p-3">
                  <div className="text-[11px] text-amber-400 mb-1.5">🐉 今日上龙虎榜</div>
                  {data!.lhb.map((r, i) => {
                    const net = typeof r.net_buy === 'number' ? r.net_buy : parseFloat(r.net_buy) || 0
                    return (
                      <div key={i} className="text-xs text-gray-300 flex flex-wrap items-center gap-x-3">
                        <span className={`font-bold ${net >= 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                          净{net >= 0 ? '买' : '卖'} {Math.abs(net).toFixed(2)}亿
                        </span>
                        <span className="text-gray-500">{r.reason}</span>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* 板块 / 题材 */}
              {(matched || Object.keys(data!.ths_hot ?? {}).length > 0) && (
                <div className="bg-gray-800/40 rounded-lg p-3 space-y-1.5">
                  {matched && (
                    <div className="text-xs text-gray-300">
                      🏭 所属板块「<b className="text-gray-200">{matched.name}</b>」今日 <b className={upDownCls(parseFloat(matched.pct))}>{matched.pct}</b>，
                      在 {matched.total} 个行业中排第 <b className="text-gray-200">{matched.rank}</b> 位 · 领涨 {matched.leader}
                    </div>
                  )}
                  {Object.entries(data!.ths_hot ?? {}).map(([dt, themes]) => (
                    <div key={dt} className="text-xs text-gray-400">
                      🔥 当日热点：{(themes as string[]).slice(0, 8).join('、')}
                    </div>
                  ))}
                </div>
              )}

              {/* 消息面 */}
              {((data!.news ?? []).length > 0 || (data!.announcements ?? []).length > 0) && (
                <div className="bg-gray-800/40 rounded-lg p-3 space-y-1">
                  <div className="text-[11px] text-gray-500 mb-1">📰 当日消息</div>
                  {(data!.announcements ?? []).map((a, i) => (
                    <div key={`a${i}`} className="text-xs text-gray-400 truncate">📋 [{a.date}] {a.title}</div>
                  ))}
                  {(data!.news ?? []).map((n, i) => (
                    <div key={`n${i}`} className="text-xs text-gray-400 truncate">· [{n.time}] {n.title}</div>
                  ))}
                </div>
              )}

              {/* AI 单日叙述 */}
              <div className="bg-gray-950/60 border border-gray-800 rounded-lg p-4">
                <div className="text-xs font-medium text-indigo-300 mb-2 flex items-center gap-2">
                  🤖 AI 单日复盘
                  {streaming && <span className="animate-pulse text-blue-400">生成中…</span>}
                </div>
                {report ? (
                  <div className="report-content prose prose-invert prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
                  </div>
                ) : (
                  <div className="text-xs text-gray-600">{streaming ? '' : '等待 AI 叙述…'}</div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
