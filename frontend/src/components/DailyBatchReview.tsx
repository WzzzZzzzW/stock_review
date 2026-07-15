/**
 * 今日批量复盘面板
 * 分两个视角：
 *   「我的持仓·自选」(默认) —— 复盘的本体，回答「我手里/我盯的票今天怎么样」
 *   「今日强势股 ⚠️」      —— 概念龙头/龙虎榜/行业领涨，本质是当日涨得最猛的，追高需谨慎，按需查看
 * 调用 /api/review/quick-batch 展示多维技术数据
 */
import { useState, useEffect, useCallback } from 'react'
import { watchlistStore } from '../stores/watchlistStore'

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface StockToday {
  date?:       string
  price?:      number
  open?:       number
  high?:       number
  low?:        number
  close?:      number
  pct_change?: number
  volume?:     number
  turn?:       number
  amount?:     number
  prev_close?: number
  name?:       string
}

interface Technical {
  ma5?:         number | null
  ma20?:        number | null
  ma60?:        number | null
  ma5_pct?:     number | null
  ma20_pct?:    number | null
  ma60_pct?:    number | null
  rsi14?:       number | null
  macd_hist?:   number | null
  macd_status?: string
  bb_pct?:      number | null
  vol_ratio?:   number | null
}

interface Trend {
  streak?:    number
  above_ma5?:  boolean
  above_ma20?: boolean
  above_ma60?: boolean
  tags?:      string[]
}

interface BatchStock {
  symbol:    string
  name:      string
  source:    string   // 自选 | 持仓 | 推荐
  today:     StockToday
  technical: Technical
  trend:     Trend
  error?:    string | null
}

interface BatchResult {
  stocks:         BatchStock[]
  date:           string
  updated_at:     string
  is_market_open: boolean
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────

const pctColor = (v?: number | null) =>
  v == null ? 'text-gray-500' : v > 0 ? 'text-red-400' : v < 0 ? 'text-emerald-400' : 'text-gray-400'

const pctText = (v?: number | null) =>
  v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`

const numFmt = (v?: number | null, digits = 2) =>
  v == null ? '--' : v.toFixed(digits)

function rsiColor(rsi?: number | null) {
  if (rsi == null) return 'text-gray-500'
  if (rsi >= 70)  return 'text-red-400'
  if (rsi <= 30)  return 'text-emerald-400'
  return 'text-gray-300'
}

function macdBadge(status?: string) {
  if (!status) return null
  const cfg: Record<string, string> = {
    '金叉': 'bg-red-900/40 text-red-300',
    '死叉': 'bg-emerald-900/40 text-emerald-300',
    '多头': 'bg-red-900/20 text-red-400/70',
    '空头': 'bg-emerald-900/20 text-emerald-400/70',
  }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cfg[status] ?? 'bg-gray-800 text-gray-500'}`}>
      {status}
    </span>
  )
}

function sourceBadge(source: string) {
  const cfg: Record<string, string> = {
    '自选': 'bg-blue-900/40 text-blue-300 border-blue-800',
    '持仓': 'bg-yellow-900/40 text-yellow-300 border-yellow-800',
    '强势': 'bg-purple-900/40 text-purple-300 border-purple-800',
  }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border shrink-0 ${cfg[source] ?? 'bg-gray-800 text-gray-500 border-gray-700'}`}>
      {source}
    </span>
  )
}

function streakText(streak?: number) {
  if (!streak) return <span className="text-gray-600">--</span>
  return streak > 0
    ? <span className="text-red-400">连涨{streak}天</span>
    : <span className="text-emerald-400">连跌{Math.abs(streak)}天</span>
}

function maPos(above5?: boolean, above20?: boolean, above60?: boolean) {
  const count = [above5, above20, above60].filter(Boolean).length
  if (count === 3) return <span className="text-red-400">三线上方 ▲</span>
  if (count === 2) return <span className="text-orange-400">2线上方</span>
  if (count === 1) return <span className="text-gray-400">1线上方</span>
  return <span className="text-emerald-400">三线下方 ▼</span>
}

// ── 读取本地数据 ──────────────────────────────────────────────────────────────

function readWatchlist(): string[] {
  // 直接复用全局自选 store（watchlist_v2，含旧 v1 自动迁移），避免读到过期的旧 key
  try {
    return watchlistStore.getAll().map(i => i.code).filter(Boolean)
  } catch { return [] }
}

async function fetchPortfolioSymbols(): Promise<string[]> {
  try {
    const res = await fetch('/api/portfolio')
    if (!res.ok) return []
    const data = await res.json()
    return (data.positions ?? []).map((p: any) => p.symbol).filter(Boolean)
  } catch { return [] }
}

async function fetchRecommendSymbols(): Promise<string[]> {
  try {
    const res = await fetch('/api/watchlist/recommend')
    if (!res.ok) return []
    const data = await res.json()
    return (data.stocks ?? []).map((s: any) => s.symbol).filter(Boolean)
  } catch { return [] }
}

// ── 主组件 ────────────────────────────────────────────────────────────────────

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
}

type Tab = 'mine' | 'strong'

export default function DailyBatchReview({ onSelectStock }: Props) {
  const [tab,       setTab]       = useState<Tab>('mine')
  const [mine,      setMine]      = useState<BatchResult | null>(null)
  const [strong,    setStrong]    = useState<BatchResult | null>(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [sortKey,   setSortKey]   = useState<'pct' | 'rsi' | 'vol' | 'source'>('source')

  const result = tab === 'mine' ? mine : strong

  const load = useCallback(async (which: Tab) => {
    setLoading(true)
    setError(null)

    try {
      let symbols: string[]
      let sources: { symbol: string; source: string }[]

      if (which === 'mine') {
        // 复盘本体：持仓 + 自选
        const portfolio = await fetchPortfolioSymbols()
        const watchlist = readWatchlist()
        const symbolSources: Record<string, Set<string>> = {}
        const addSym = (syms: string[], src: string) => {
          syms.forEach(s => {
            if (!symbolSources[s]) symbolSources[s] = new Set()
            symbolSources[s].add(src)
          })
        }
        addSym(portfolio, '持仓')
        addSym(watchlist, '自选')
        symbols = Object.keys(symbolSources)
        // 优先级：持仓 > 自选
        sources = symbols.map(sym => ({
          symbol: sym,
          source: symbolSources[sym].has('持仓') ? '持仓' : '自选',
        }))
      } else {
        // 今日强势股（概念龙头/龙虎榜/行业领涨）—— 追高需谨慎
        symbols = await fetchRecommendSymbols()
        sources = symbols.map(sym => ({ symbol: sym, source: '强势' }))
      }

      const empty: BatchResult = { stocks: [], date: new Date().toISOString().slice(0, 10), updated_at: '', is_market_open: false }
      if (symbols.length === 0) {
        which === 'mine' ? setMine(empty) : setStrong(empty)
        return
      }

      const res = await fetch('/api/review/quick-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols, sources }),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: BatchResult = await res.json()
      which === 'mine' ? setMine(data) : setStrong(data)
    } catch (e: any) {
      setError(e.message ?? '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 初次加载「我的」
  useEffect(() => { load('mine') }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // 切到「强势股」且尚未加载过时，懒加载一次
  useEffect(() => {
    if (tab === 'strong' && !strong && !loading) load('strong')
  }, [tab])  // eslint-disable-line react-hooks/exhaustive-deps

  // 排序
  const sorted = result ? [...result.stocks].sort((a, b) => {
    if (sortKey === 'pct') {
      return (b.today?.pct_change ?? 0) - (a.today?.pct_change ?? 0)
    }
    if (sortKey === 'rsi') {
      return (b.technical?.rsi14 ?? 50) - (a.technical?.rsi14 ?? 50)
    }
    if (sortKey === 'vol') {
      return (b.technical?.vol_ratio ?? 1) - (a.technical?.vol_ratio ?? 1)
    }
    // source: 持仓 > 自选 > 强势
    const order: Record<string, number> = { '持仓': 0, '自选': 1, '强势': 2 }
    return (order[a.source] ?? 9) - (order[b.source] ?? 9)
  }) : []

  const hasData = result && result.stocks.length > 0

  // ── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setCollapsed(c => !c)}
            className="text-white font-semibold text-sm flex items-center gap-2"
          >
            <span>📊 今日批量复盘</span>
            <span className="text-gray-600 text-xs">{collapsed ? '▶' : '▼'}</span>
          </button>
          {result && (
            <span className="text-xs text-gray-600">
              {result.date} · 共 {result.stocks.length} 只
            </span>
          )}
          {result?.is_market_open && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-900/50 border border-green-800 text-green-400 animate-pulse">
              交易中
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {result?.updated_at && (
            <span className="text-xs text-gray-600">更新于 {result.updated_at}</span>
          )}
          <button
            onClick={() => load(tab)}
            disabled={loading}
            className="text-xs text-blue-400 hover:text-blue-300 disabled:text-gray-600 transition-colors"
          >
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <>
          {/* 视角切换 Tab */}
          <div className="flex items-center gap-1 px-5 pt-3">
            <button
              onClick={() => setTab('mine')}
              className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${
                tab === 'mine' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
              }`}
            >
              我的持仓·自选
            </button>
            <button
              onClick={() => setTab('strong')}
              className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${
                tab === 'strong' ? 'bg-purple-700 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
              }`}
            >
              多维候选池
            </button>
          </div>

          {/* 多维候选说明 */}
          {tab === 'strong' && (
            <div className="mx-5 mt-3 px-3 py-2 rounded-lg bg-amber-900/20 border border-amber-800/50 text-[11px] text-amber-300/90 leading-relaxed">
              候选由题材、龙虎榜、行业、趋势、量价和风险共同筛选，涨跌幅只是一项证据。
              表格用于核对分项，不代表看到红盘就追入；最终动作以统一决策分和触发条件为准。
            </div>
          )}

          {/* 错误 */}
          {error && (
            <div className="px-5 py-4 text-sm text-red-400">
              ⚠️ {error}
            </div>
          )}

          {/* 加载中 */}
          {loading && !result && (
            <div className="px-5 py-8 flex items-center gap-3 text-sm text-gray-500">
              <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"/>
              正在采集技术数据（约 30~60 秒）…
            </div>
          )}

          {/* 空状态 */}
          {!loading && !error && result && result.stocks.length === 0 && (
            <div className="px-5 py-8 text-sm text-gray-600 text-center">
              {tab === 'mine'
                ? '持仓和自选中暂无股票，先去加自选 / 录入持仓吧'
                : '暂无通过多维筛选的候选（盘前或数据源未就绪）'}
            </div>
          )}

          {/* 数据表格 */}
          {hasData && (
            <>
              {/* 排序控制 */}
              <div className="flex items-center gap-2 px-5 py-2 border-b border-gray-800/60">
                <span className="text-xs text-gray-600">排序：</span>
                {([['source', '来源'], ['pct', '涨跌幅'], ['rsi', 'RSI'], ['vol', '量比']] as const).map(([k, l]) => (
                  <button
                    key={k}
                    onClick={() => setSortKey(k)}
                    className={`text-xs px-2 py-0.5 rounded transition-colors ${
                      sortKey === k ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    {l}
                  </button>
                ))}
              </div>

              {/* 表格 */}
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-600 border-b border-gray-800/60">
                      <th className="text-left px-4 py-2 font-normal w-36">股票</th>
                      <th className="text-right px-3 py-2 font-normal">今日涨跌</th>
                      <th className="text-right px-3 py-2 font-normal">现价</th>
                      <th className="text-right px-3 py-2 font-normal">量比</th>
                      <th className="text-right px-3 py-2 font-normal">RSI</th>
                      <th className="text-center px-3 py-2 font-normal">MACD</th>
                      <th className="text-right px-3 py-2 font-normal">MA位置</th>
                      <th className="text-right px-3 py-2 font-normal">布林%B</th>
                      <th className="text-right px-3 py-2 font-normal">趋势</th>
                      <th className="text-left px-3 py-2 font-normal">信号</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map(stock => {
                      const t = stock.today
                      const tech = stock.technical
                      const trend = stock.trend
                      const pct = t?.pct_change ?? null
                      const price = t?.price ?? t?.close ?? null

                      if (stock.error) {
                        return (
                          <tr key={stock.symbol} className="border-b border-gray-800/40 opacity-40">
                            <td className="px-4 py-2.5">
                              <div className="flex items-center gap-2">
                                {sourceBadge(stock.source)}
                                <span className="font-mono text-gray-400">{stock.symbol}</span>
                              </div>
                            </td>
                            <td colSpan={9} className="px-3 py-2.5 text-gray-600">数据采集失败</td>
                          </tr>
                        )
                      }

                      return (
                        <tr
                          key={stock.symbol}
                          className="border-b border-gray-800/40 hover:bg-gray-800/30 transition-colors cursor-pointer"
                          onClick={() => onSelectStock?.(stock.symbol, stock.name)}
                        >
                          {/* 股票名称 */}
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-2">
                              {sourceBadge(stock.source)}
                              <div>
                                <div className="text-gray-200 font-medium truncate max-w-[80px]" title={stock.name}>
                                  {stock.name || stock.symbol}
                                </div>
                                <div className="text-gray-600 font-mono">{stock.symbol}</div>
                              </div>
                            </div>
                          </td>

                          {/* 涨跌幅 */}
                          <td className={`text-right px-3 py-2.5 font-mono font-bold ${pctColor(pct)}`}>
                            {pctText(pct)}
                          </td>

                          {/* 现价 */}
                          <td className="text-right px-3 py-2.5 font-mono text-gray-300">
                            {price != null ? price.toFixed(2) : '--'}
                          </td>

                          {/* 量比 */}
                          <td className={`text-right px-3 py-2.5 font-mono ${
                            (tech?.vol_ratio ?? 1) >= 2 ? 'text-red-400 font-bold' :
                            (tech?.vol_ratio ?? 1) >= 1.5 ? 'text-orange-400' :
                            (tech?.vol_ratio ?? 1) <= 0.5 ? 'text-gray-600' : 'text-gray-400'
                          }`}>
                            {numFmt(tech?.vol_ratio, 1)}x
                          </td>

                          {/* RSI */}
                          <td className={`text-right px-3 py-2.5 font-mono ${rsiColor(tech?.rsi14)}`}>
                            {numFmt(tech?.rsi14, 1)}
                          </td>

                          {/* MACD状态 */}
                          <td className="text-center px-3 py-2.5">
                            {macdBadge(tech?.macd_status)}
                          </td>

                          {/* MA位置 */}
                          <td className="text-right px-3 py-2.5">
                            {maPos(trend?.above_ma5, trend?.above_ma20, trend?.above_ma60)}
                          </td>

                          {/* 布林%B */}
                          <td className={`text-right px-3 py-2.5 font-mono ${
                            tech?.bb_pct != null && tech.bb_pct >= 0.9 ? 'text-red-400' :
                            tech?.bb_pct != null && tech.bb_pct <= 0.1 ? 'text-emerald-400' : 'text-gray-400'
                          }`}>
                            {tech?.bb_pct != null ? `${(tech.bb_pct * 100).toFixed(0)}%` : '--'}
                          </td>

                          {/* 连涨/连跌 */}
                          <td className="text-right px-3 py-2.5">
                            {streakText(trend?.streak)}
                          </td>

                          {/* 信号标签 */}
                          <td className="px-3 py-2.5">
                            <div className="flex flex-wrap gap-1">
                              {(trend?.tags ?? []).slice(0, 2).map((tag, i) => (
                                <span key={i} className="text-[10px] text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded whitespace-nowrap">
                                  {tag}
                                </span>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* 说明 */}
              <div className="px-5 py-3 text-[11px] text-gray-700 border-t border-gray-800/60">
                技术指标基于近90日日K计算 · 量比=今日成交量/近20日均量 · 布林%B=0%贴下轨/100%贴上轨 · 点击任意行进入深度复盘
                {!result.is_market_open && ' · 收盘后数据按日缓存，次日交易后自动更新'}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
