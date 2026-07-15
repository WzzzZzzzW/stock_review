import { useState, useMemo, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import CandlestickChart from '../components/CandlestickChart'
import DailyBatchReview from '../components/DailyBatchReview'
import ErrorBoundary from '../components/ErrorBoundary'
import SearchForm from '../components/SearchForm'
import StatCard from '../components/StatCard'
import StrategyBacktest from '../components/StrategyBacktest'
import BrainMatchPanel from '../components/BrainMatchPanel'
import ReviewVerdictCard from '../components/ReviewVerdictCard'
import YesterdayReview from '../components/YesterdayReview'
import { useReview } from '../hooks/useReview'
import type { FinancialScore, OhlcvBar } from '../types'

interface Props {
  defaultSymbol?: string
  defaultName?:   string
}

// 板块颜色 mapping
const BOARD_COLOR: Record<string, string> = {
  '沪市主板': 'bg-red-900/40 text-red-300 border-red-800',
  '深市主板': 'bg-blue-900/40 text-blue-300 border-blue-800',
  '创业板':   'bg-green-900/40 text-green-300 border-green-800',
  '科创板':   'bg-yellow-900/40 text-yellow-300 border-yellow-800',
  '北交所':   'bg-purple-900/40 text-purple-300 border-purple-800',
}

function getBoard(symbol: string): string {
  if (symbol.startsWith('688') || symbol.startsWith('689')) return '科创板'
  if (symbol.startsWith('6')) return '沪市主板'
  if (symbol.startsWith('3')) return '创业板'
  if (symbol.startsWith('8') || symbol.startsWith('4')) return '北交所'
  return '深市主板'
}

// 财务健康评分卡（纯算法，客观）
const GRADE_CONFIG = {
  A: { bg: 'bg-emerald-900/30', border: 'border-emerald-700', text: 'text-emerald-400', badge: 'bg-emerald-700', label: '优秀', emoji: '🟢' },
  B: { bg: 'bg-blue-900/30',    border: 'border-blue-700',    text: 'text-blue-400',    badge: 'bg-blue-700',    label: '良好', emoji: '🔵' },
  C: { bg: 'bg-yellow-900/20',  border: 'border-yellow-700',  text: 'text-yellow-400',  badge: 'bg-yellow-700',  label: '一般', emoji: '🟡' },
  D: { bg: 'bg-orange-900/30',  border: 'border-orange-700',  text: 'text-orange-400',  badge: 'bg-orange-700',  label: '较差', emoji: '🟠' },
  F: { bg: 'bg-red-900/30',     border: 'border-red-800',     text: 'text-red-400',     badge: 'bg-red-800',     label: '极差', emoji: '🔴' },
}

function FinancialScoreCard({ fs }: { fs: FinancialScore }) {
  const cfg = GRADE_CONFIG[fs.grade] ?? GRADE_CONFIG['C']
  const isDanger = fs.grade === 'D' || fs.grade === 'F'

  return (
    <div className={`rounded-xl border p-5 ${cfg.bg} ${cfg.border}`}>
      {/* 标题行 */}
      <div className="flex items-center gap-3 mb-4">
        <span className="text-lg">{cfg.emoji}</span>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-300">客观财务健康评分</span>
            <span className={`text-xs px-2 py-0.5 rounded font-bold text-white ${cfg.badge}`}>
              {fs.grade}级 · {cfg.label}
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">由纯算法计算，基于真实财务数据，不受 AI 影响</p>
        </div>
        {/* 分数条 */}
        <div className="ml-auto text-right">
          <span className={`text-2xl font-bold tabular-nums ${cfg.text}`}>{fs.score}</span>
          <span className="text-xs text-gray-600 ml-1">/ 100</span>
          <div className="w-24 h-1.5 bg-gray-800 rounded-full mt-1 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${cfg.badge}`}
              style={{ width: `${fs.score}%` }}
            />
          </div>
        </div>
      </div>

      {/* 风险警告 */}
      {(fs.flags ?? []).length > 0 && (
        <div className="mb-3">
          <p className="text-xs font-semibold text-orange-400 mb-1.5">⚠️ 风险警告</p>
          <div className="space-y-1">
            {(fs.flags ?? []).map((f, i) => (
              <div key={i} className="flex items-start gap-2 text-xs text-gray-300">
                <span className="text-orange-500 mt-0.5 shrink-0">•</span>
                <span>{f}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 亮点 */}
      {(fs.positives ?? []).length > 0 && (
        <div className="mb-3">
          <p className="text-xs font-semibold text-emerald-400 mb-1.5">✅ 财务亮点</p>
          <div className="space-y-1">
            {(fs.positives ?? []).map((p, i) => (
              <div key={i} className="flex items-start gap-2 text-xs text-gray-300">
                <span className="text-emerald-500 mt-0.5 shrink-0">•</span>
                <span>{p}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 危险警示横幅 */}
      {isDanger && (
        <div className="mt-3 p-2.5 bg-red-900/40 border border-red-800 rounded-lg">
          <p className="text-xs text-red-300 font-semibold">
            🚫 财务评分 {fs.grade} 级：财务状况{fs.grade === 'F' ? '极差，存在重大风险' : '较差，风险较高'}，不建议普通投资者参与
          </p>
        </div>
      )}
    </div>
  )
}

// ── 按日拆解 ─────────────────────────────────────────────────────────────────

/** 计算每根 K 线的量比（相对前 20 日均量） */
function computeVolRatios(bars: OhlcvBar[]): number[] {
  return bars.map((bar, i) => {
    if (i === 0) return 1
    const slice = bars.slice(Math.max(0, i - 20), i)
    const avg   = slice.reduce((s, b) => s + b.volume, 0) / slice.length
    return avg > 0 ? bar.volume / avg : 1
  })
}

function barSignal(pct: number, volRatio: number): { emoji: string; label: string; color: string } {
  const abs = Math.abs(pct)
  if (pct >= 9.5)  return { emoji: '🚀', label: '涨停',   color: 'text-red-300 font-bold' }
  if (pct <= -9.5) return { emoji: '💀', label: '跌停',   color: 'text-emerald-300 font-bold' }
  const heavy = volRatio >= 1.5
  const light = volRatio <= 0.7
  if (pct > 3  && heavy) return { emoji: '🔥', label: '放量大涨', color: 'text-red-400' }
  if (pct > 0  && heavy) return { emoji: '📈', label: '放量上涨', color: 'text-red-400' }
  if (pct > 0  && light) return { emoji: '↗️', label: '缩量上涨', color: 'text-red-400/60' }
  if (pct < -3 && heavy) return { emoji: '⚠️', label: '放量大跌', color: 'text-emerald-400' }
  if (pct < 0  && heavy) return { emoji: '📉', label: '放量下跌', color: 'text-emerald-400' }
  if (pct < 0  && light) return { emoji: '↘️', label: '缩量下跌', color: 'text-emerald-400/60' }
  if (abs < 0.3)         return { emoji: '➡️', label: '横盘',     color: 'text-gray-500' }
  return pct > 0
    ? { emoji: '↗️', label: '小涨', color: 'text-red-400/70' }
    : { emoji: '↘️', label: '小跌', color: 'text-emerald-400/70' }
}

function DailyBreakdown({ ohlcv, keyEvents }: { ohlcv: OhlcvBar[]; keyEvents?: any[] }) {
  const [expanded, setExpanded]     = useState(false)
  const [sortDesc,  setSortDesc]    = useState(true)  // 默认最新在前

  const keyEventDates = useMemo(
    () => new Set((keyEvents ?? []).map((e: any) => e.date as string)),
    [keyEvents]
  )

  const volRatios = useMemo(() => computeVolRatios(ohlcv), [ohlcv])

  // 构建每日行
  const rows = useMemo(() => {
    const base = ohlcv.map((bar, i) => ({
      ...bar,
      volRatio: volRatios[i],
      isKeyEvent: keyEventDates.has(bar.date),
    }))
    return sortDesc ? [...base].reverse() : base
  }, [ohlcv, volRatios, keyEventDates, sortDesc])

  const visibleRows = expanded ? rows : rows.slice(0, 30)
  const totalRows   = rows.length

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800">
        <h3 className="text-sm font-medium text-gray-400 flex items-center gap-2">
          🗓️ 按日拆解
          <span className="text-xs text-gray-600 font-normal">共 {totalRows} 个交易日</span>
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSortDesc(d => !d)}
            className="text-xs text-gray-500 hover:text-white bg-gray-800 hover:bg-gray-700 px-2.5 py-1 rounded-lg transition-colors"
          >
            {sortDesc ? '最新在前 ↓' : '最早在前 ↑'}
          </button>
        </div>
      </div>

      {/* 表头 */}
      <div className="grid grid-cols-[6rem_1fr_1fr_1fr_1fr_5rem_7rem] gap-x-3 px-4 py-2 text-[10px] text-gray-600 border-b border-gray-800/60 font-medium">
        <span>日期</span>
        <span className="text-right">收盘</span>
        <span className="text-right">涨跌幅</span>
        <span className="text-right">成交量(万手)</span>
        <span className="text-right">量比</span>
        <span className="text-right">MA20</span>
        <span>信号</span>
      </div>

      {/* 数据行 */}
      <div className="divide-y divide-gray-800/40">
        {visibleRows.map(row => {
          const sig    = barSignal(row.pct_change, row.volRatio)
          const isUp   = row.pct_change > 0
          const isDn   = row.pct_change < 0
          const aboveMA = row.ma20 > 0 ? row.close >= row.ma20 : null
          const rowBg  = row.isKeyEvent ? 'bg-amber-900/10' : ''

          return (
            <div key={row.date}
              className={`grid grid-cols-[6rem_1fr_1fr_1fr_1fr_5rem_7rem] gap-x-3 px-4 py-2 text-xs items-center hover:bg-gray-800/30 transition-colors ${rowBg}`}
            >
              {/* 日期 */}
              <span className="text-gray-500 font-mono text-[11px] flex items-center gap-1">
                {row.isKeyEvent && <span className="text-amber-500">●</span>}
                {row.date}
              </span>

              {/* 收盘价 */}
              <span className={`text-right font-mono ${isUp ? 'text-red-400' : isDn ? 'text-emerald-400' : 'text-gray-300'}`}>
                {row.close.toFixed(2)}
              </span>

              {/* 涨跌幅 */}
              <span className={`text-right font-mono font-semibold ${isUp ? 'text-red-400' : isDn ? 'text-emerald-400' : 'text-gray-400'}`}>
                {row.pct_change > 0 ? '+' : ''}{row.pct_change.toFixed(2)}%
              </span>

              {/* 成交量 */}
              <span className="text-right text-gray-500 font-mono">
                {(row.volume / 10000).toFixed(1)}
              </span>

              {/* 量比 */}
              <span className={`text-right font-mono ${
                row.volRatio >= 2   ? 'text-red-400 font-bold' :
                row.volRatio >= 1.5 ? 'text-red-400/80' :
                row.volRatio <= 0.5 ? 'text-gray-600' :
                'text-gray-400'
              }`}>
                {row.volRatio.toFixed(2)}x
              </span>

              {/* MA20 */}
              <span className={`text-right font-mono text-[11px] ${
                aboveMA === true  ? 'text-red-400/70' :
                aboveMA === false ? 'text-emerald-400/70' :
                'text-gray-600'
              }`}>
                {row.ma20 > 0 ? row.ma20.toFixed(2) : '--'}
              </span>

              {/* 信号 */}
              <span className={`flex items-center gap-1 ${sig.color}`}>
                <span>{sig.emoji}</span>
                <span className="text-[11px]">{sig.label}</span>
              </span>
            </div>
          )
        })}
      </div>

      {/* 展开/折叠 */}
      {totalRows > 30 && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="w-full py-2.5 text-xs text-gray-500 hover:text-white hover:bg-gray-800/40 transition-colors border-t border-gray-800"
        >
          {expanded ? `▲ 收起（只显示30条）` : `▼ 展开全部 ${totalRows} 个交易日`}
        </button>
      )}

      {/* 图例 */}
      <div className="px-5 py-2.5 bg-gray-900/50 border-t border-gray-800 flex flex-wrap gap-4 text-[10px] text-gray-600">
        <span>量比 ≥1.5 = 放量 · ≤0.7 = 缩量</span>
        <span>MA20颜色：红=价格在均线上 / 绿=在均线下</span>
        <span>● 黄色行 = 关键异动日</span>
      </div>
    </div>
  )
}

// 龙虎榜上榜记录
function LhbCard({ records }: { records: any[] }) {
  return (
    <div className="bg-gray-900 border border-amber-900/50 rounded-xl p-5">
      <h3 className="text-sm font-medium text-amber-400 mb-4 flex items-center gap-2">
        🐉 龙虎榜上榜记录
        <span className="text-xs text-gray-500 font-normal">区间内游资/机构席位介入情况</span>
      </h3>
      <div className="space-y-2">
        {records.map((r, i) => {
          const netBuy = typeof r.net_buy === 'number' ? r.net_buy : parseFloat(r.net_buy) || 0
          const isBuy = netBuy >= 0
          return (
            <div key={i} className="bg-gray-800/50 rounded-lg p-3 space-y-1.5">
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-xs text-gray-500 font-mono w-24 shrink-0">{r.date}</span>
                <span className={`text-sm font-bold tabular-nums ${r.pct_chg > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                  {r.pct_chg > 0 ? '+' : ''}{r.pct_chg?.toFixed(2)}%
                </span>
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${isBuy ? 'bg-red-900/40 text-red-300' : 'bg-emerald-900/40 text-emerald-300'}`}>
                  净{isBuy ? '买入' : '卖出'} {Math.abs(netBuy).toFixed(2)}亿
                </span>
                <span className="text-xs text-gray-600 ml-auto">
                  上榜后5日：<span className={parseFloat(r.after_5d) > 0 ? 'text-red-400' : 'text-emerald-400'}>
                    {typeof r.after_5d === 'number' ? `${r.after_5d > 0 ? '+' : ''}${r.after_5d.toFixed(2)}%` : r.after_5d}
                  </span>
                </span>
              </div>
              <p className="text-xs text-gray-400 pl-24">{r.reason}</p>
            </div>
          )
        })}
      </div>
      <p className="text-[11px] text-gray-600 mt-3">净买额为负=大户合计净卖出（拉高出货特征）；上榜后5日涨跌反映事件后续走势</p>
    </div>
  )
}

// 异动节点 → 一句话「结构解读」（纯前端计算，不耗 AI）
function summarizeKeyEvents(events: any[], ohlcv: OhlcvBar[]): string | null {
  if (!events || events.length === 0 || !ohlcv || ohlcv.length < 2) return null
  const bigUp   = events.filter(e => e.direction === '大涨')
  const bigDown = events.filter(e => e.direction === '大跌')
  if (bigUp.length === 0 && bigDown.length === 0) return null

  const first = Number(ohlcv[0]?.close) || 0
  const last  = Number(ohlcv[ohlcv.length - 1]?.close) || 0
  const rangePct = first > 0 ? ((last - first) / first) * 100 : 0
  const moveTxt  = `股价${rangePct >= 0 ? '累计上涨' : '累计下跌'} ${Math.abs(rangePct).toFixed(0)}%（${first.toFixed(0)}→${last.toFixed(0)}）`

  // 时间序最后一个「大」异动决定结尾信号
  const bigs = [...events]
    .filter(e => e.direction === '大涨' || e.direction === '大跌')
    .sort((a, b) => (a.date < b.date ? -1 : 1))
  const lastBig = bigs[bigs.length - 1]
  let signal = ''
  if (lastBig?.direction === '大跌' && bigUp.length >= 2) {
    signal = `近端 ${lastBig.date} 高位放量大跌，量价背离，警惕见顶回落。`
  } else if (lastBig?.direction === '大涨' && bigDown.length >= 1) {
    signal = `近端 ${lastBig.date} 放量上涨修复，关注能否站稳放量平台。`
  } else if (lastBig?.direction === '大涨') {
    signal = `量价齐升，趋势仍由放量上涨主导。`
  } else if (lastBig?.direction === '大跌') {
    signal = `放量下跌占主导，承压明显，留意止跌信号。`
  }

  const counts = `区间内 ${bigUp.length} 次放量大涨` + (bigDown.length ? `、${bigDown.length} 次放量大跌` : '')
  return `${counts}；${moveTxt}。${signal}`
}

export default function ReviewPage({ defaultSymbol = '', defaultName = '' }: Props) {
  const { mutate, data, streamedReport, isPending, isStreaming, error } = useReview()
  const [reviewSymbol, setReviewSymbol] = useState(defaultSymbol)
  const [reviewName,   setReviewName]   = useState(defaultName)
  const [showDetail,   setShowDetail]   = useState(false)   // 按日拆解/策略回测等明细，默认折叠

  // keep-alive 模式下，从其他页面跳转过来时 prop 变化需要同步
  const prevSymbolRef = useRef(defaultSymbol)
  useEffect(() => {
    if (defaultSymbol && defaultSymbol !== prevSymbolRef.current) {
      prevSymbolRef.current = defaultSymbol
      setReviewSymbol(defaultSymbol)
      setReviewName(defaultName)
      // 自动触发90天复盘
      const today = new Date()
      const end   = today.toISOString().slice(0, 10).replace(/-/g, '')
      const start = new Date(today.getTime() - 90 * 86400000).toISOString().slice(0, 10).replace(/-/g, '')
      mutate({ symbol: defaultSymbol, start, end }, defaultName)
    }
  }, [defaultSymbol, defaultName, mutate])

  const handleSubmit = (symbol: string, start: string, end: string) => {
    mutate({ symbol, start, end }, reviewName)
  }

  // 从批量复盘面板跳转到单股深度复盘
  const handleSelectFromBatch = (symbol: string, name: string) => {
    setReviewSymbol(symbol)
    setReviewName(name)
    // 自动触发默认90天复盘
    const today = new Date()
    const end   = today.toISOString().slice(0, 10).replace(/-/g, '')
    const start = new Date(today.getTime() - 90 * 86400000).toISOString().slice(0, 10).replace(/-/g, '')
    mutate({ symbol, start, end }, name)
    // 滚动到搜索区
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const summary  = data?.price_summary
  const industry = data?.industry
  const board    = data ? getBoard(data.symbol) : ''
  const boardCls = BOARD_COLOR[board] ?? 'bg-gray-800 text-gray-400 border-gray-700'

  return (
    <div className="min-h-screen bg-gray-950 px-4 py-8">
      <div className="max-w-5xl mx-auto space-y-6">

        {/* 标题 */}
        <div>
          <h1 className="text-2xl font-bold text-white">股票复盘工具</h1>
          <p className="text-sm text-gray-500 mt-1">六维深度分析 · 涨跌归因 · AI 复盘报告</p>
        </div>

        {/* 今日批量复盘面板 */}
        <ErrorBoundary name="今日批量复盘">
          <DailyBatchReview onSelectStock={handleSelectFromBatch} />
        </ErrorBoundary>

        {/* 搜索表单 */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <SearchForm
            onSubmit={handleSubmit}
            loading={isPending}
            defaultSymbol={reviewSymbol}
            defaultName={reviewName}
          />
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-xl p-4 text-red-300 text-sm">
            {error.message}
          </div>
        )}

        {/* 加载中（阶段一：采集数据） */}
        {isPending && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4"/>
            <div className="text-gray-300 text-sm font-medium">正在采集多维度数据…</div>
            <div className="text-gray-500 text-xs mt-2">包含行情 · 财务 · 行业 · 涨跌归因，约需 15~30 秒</div>
          </div>
        )}

        {/* 结果展示（阶段一数据到位后立即渲染，AI 报告在阶段二流式追加） */}
        {data && !isPending && (
          <ErrorBoundary name="复盘结果">
            <>
              {/* 股票标题 + 行业标签 */}
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
                <div className="flex items-start gap-3 flex-wrap">
                  <h2 className="text-xl font-bold text-white">{data.name}</h2>
                  <span className="text-gray-400 text-sm mt-1">{data.symbol}</span>
                  <span className={`text-xs px-2 py-0.5 rounded border mt-0.5 ${boardCls}`}>{board}</span>
                  {industry?.name && (
                    <span className="text-xs px-2 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-400 mt-0.5">
                      {industry.name.replace(/^[A-Z][0-9]+ /, '')}
                    </span>
                  )}
                  <span className="text-gray-600 text-xs mt-1 ml-auto">
                    {data.period?.start} ~ {data.period?.end}
                  </span>
                </div>

                {summary && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatCard
                      label="区间涨跌幅"
                      value={`${(summary.total_return ?? 0) > 0 ? '+' : ''}${summary.total_return ?? '--'}%`}
                      positive={(summary.total_return ?? 0) > 0 ? true : (summary.total_return ?? 0) < 0 ? false : null}
                    />
                    <StatCard label="区间最高" value={`¥${summary.max_price ?? '--'}`} />
                    <StatCard label="区间最低" value={`¥${summary.min_price ?? '--'}`} />
                    <StatCard
                      label="最新 RSI(14)"
                      value={summary.latest_rsi != null ? summary.latest_rsi.toFixed(1) : '--'}
                      positive={summary.latest_rsi != null ? summary.latest_rsi > 50 : null}
                    />
                  </div>
                )}

                {/* 额外技术指标 */}
                {summary && (
                  <div className="flex flex-wrap gap-4 pt-1 text-xs text-gray-500 border-t border-gray-800">
                    <span>上涨 <b className="text-red-400">{summary.gain_days ?? '--'}</b> 天 / 下跌 <b className="text-emerald-400">{summary.loss_days ?? '--'}</b> 天</span>
                    {summary.price_vs_ma && <span>均线：{summary.price_vs_ma}</span>}
                    {summary.max_vol_date && (
                      <span>最大成交量 {summary.max_vol_date}（{(((summary.max_volume ?? 0)) / 10000).toFixed(0)}万手）</span>
                    )}
                  </div>
                )}
              </div>

              {/* 📅 昨日复盘（单日聚焦，懒加载：展开才请求）*/}
              <ErrorBoundary name="昨日复盘">
                <YesterdayReview symbol={data.symbol} name={data.name} />
              </ErrorBoundary>

              {/* 🧭 复盘速览（结论先行，纯算法毫秒级，无需等 AI）*/}
              {data.verdict && data.verdict.stance && (
                <ErrorBoundary name="复盘速览">
                  <ReviewVerdictCard verdict={data.verdict} />
                </ErrorBoundary>
              )}

              {/* K线图（叠加量价异动标记 ▲▼ + 一句话结构解读）*/}
              {(data.ohlcv ?? []).length > 0 && (
                <ErrorBoundary name="K线图">
                  <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm font-medium text-gray-400">K 线图（前复权）</h3>
                      {(data.key_events ?? []).length > 0 && (
                        <span className="text-[11px] text-gray-500">
                          <span className="text-red-400">▲</span> 放量大涨 ·
                          <span className="text-emerald-400 ml-1">▼</span> 放量大跌
                        </span>
                      )}
                    </div>
                    <CandlestickChart data={data.ohlcv} keyEvents={data.key_events ?? []} />
                    {(() => {
                      const s = summarizeKeyEvents(data.key_events ?? [], data.ohlcv ?? [])
                      return s ? (
                        <div className="mt-3 px-3 py-2 rounded-lg bg-gray-800/50 border border-gray-700/50 text-xs text-gray-300 leading-relaxed">
                          <span className="text-gray-500">📍 异动解读：</span>{s}
                        </div>
                      ) : null
                    })()}
                  </div>
                </ErrorBoundary>
              )}

              {/* 龙虎榜 */}
              {(data.lhb ?? []).length > 0 && (
                <ErrorBoundary name="龙虎榜">
                  <LhbCard records={data.lhb!} />
                </ErrorBoundary>
              )}

              {/* 客观财务评分卡（纯算法）*/}
              {data.financial_score && (
                <ErrorBoundary name="财务评分">
                  <FinancialScoreCard fs={data.financial_score} />
                </ErrorBoundary>
              )}

              {/* 🧠 脑库匹配 — 自动调用你的交易系统规则 */}
              <ErrorBoundary name="脑库匹配">
                <BrainMatchPanel context={[
                  `股票：${data.name}(${data.symbol})`,
                  industry?.name ? `行业：${industry.name}` : '',
                  board ? `板块：${board}` : '',
                  summary ? `区间涨跌：${summary.total_return?.toFixed(2)}%` : '',
                  data.financial_score ? `财务评分：${data.financial_score.score}分(${data.financial_score.grade})` : '',
                ].filter(Boolean).join('，')} />
              </ErrorBoundary>

              {/* AI 复盘报告 */}
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <h3 className="text-sm font-medium text-gray-400 mb-2 flex items-center gap-2">
                  <span>🤖 AI 六维深度复盘报告</span>
                  <span className="text-xs text-gray-600 font-normal">by GLM-4-Flash</span>
                  {isStreaming && (
                    <span className="animate-pulse text-xs text-blue-400 ml-1">AI 正在生成报告…</span>
                  )}
                </h3>
                <p className="text-xs text-gray-600 mb-5 pb-3 border-b border-gray-800">
                  ⚠️ AI 报告基于量价和财务数据生成，对公司历史事件的描述可能存在错误或遗漏。涨跌归因中标注【推测】的内容无新闻数据支撑，请自行验证。
                </p>
                <ErrorBoundary name="AI报告">
                  <div className="report-content prose prose-invert prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {streamedReport || data.report || ''}
                    </ReactMarkdown>
                  </div>
                </ErrorBoundary>
              </div>

              {/* 📋 明细数据（默认折叠，按需展开，避免主视图信息过载）*/}
              {(data.ohlcv ?? []).length > 0 && (
                <div className="bg-gray-900/60 border border-gray-800 rounded-xl overflow-hidden">
                  <button
                    onClick={() => setShowDetail(v => !v)}
                    className="w-full flex items-center justify-between px-5 py-3 text-sm text-gray-400 hover:text-white hover:bg-gray-800/40 transition-colors"
                  >
                    <span className="flex items-center gap-2">
                      📋 逐日明细 & 策略回测
                      <span className="text-xs text-gray-600 font-normal">含按日量价拆解、单股策略回测</span>
                    </span>
                    <span className="text-xs">{showDetail ? '收起 ▲' : '展开 ▼'}</span>
                  </button>
                  {showDetail && (
                    <div className="p-4 pt-0 space-y-4">
                      <ErrorBoundary name="按日拆解">
                        <DailyBreakdown ohlcv={data.ohlcv} keyEvents={data.key_events} />
                      </ErrorBoundary>
                      {(data.ohlcv ?? []).length >= 10 && (
                        <ErrorBoundary name="策略回测">
                          <StrategyBacktest ohlcv={data.ohlcv} />
                        </ErrorBoundary>
                      )}
                    </div>
                  )}
                </div>
              )}
            </>
          </ErrorBoundary>
        )}
      </div>
    </div>
  )
}
