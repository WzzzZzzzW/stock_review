/**
 * 量化专区页
 * Tab 1: 策略仓库（StrategyLibraryPage）
 * Tab 2: 策略对比（StrategyBacktest）
 * Tab 3: 选股因子（概念板块因子排名）
 * Tab 4: 我的策略（CustomStrategyPage）
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import StrategyBacktest from '../components/StrategyBacktest'
import StrategyLibraryPage from './StrategyLibraryPage'
import CustomStrategyPage from './CustomStrategyPage'
import StockSearch from '../components/StockSearch'
import type { OhlcvBar } from '../types'

// ── 类型 ──────────────────────────────────────────────────────────────────────
interface ReviewResponse {
  ohlcv: OhlcvBar[]
  [key: string]: unknown
}

interface ConceptItem {
  name:          string
  code:          string
  pct:           string
  pct_num:       number
  leader:        string
  leader_pct:    number
  company_count: number
}

interface ConceptsResponse {
  concepts:   ConceptItem[]
  updated_at: string
}

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
}

// ── 日期计算 ──────────────────────────────────────────────────────────────────
function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}${m}${day}`
}

type DateRange = '1m' | '3m' | '6m' | '1y'

function getDateRange(range: DateRange): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  if (range === '1m') start.setMonth(start.getMonth() - 1)
  else if (range === '3m') start.setMonth(start.getMonth() - 3)
  else if (range === '6m') start.setMonth(start.getMonth() - 6)
  else start.setFullYear(start.getFullYear() - 1)
  return { start: toDateStr(start), end: toDateStr(end) }
}

// ── 颜色工具 ──────────────────────────────────────────────────────────────────
function pctColor(v: number): string {
  if (v > 0) return 'text-red-400'
  if (v < 0) return 'text-emerald-400'
  return 'text-gray-400'
}

// ── Spinner ───────────────────────────────────────────────────────────────────
function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-40 text-gray-500">
      <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mr-2" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

// ── Section 1: 策略回测 ───────────────────────────────────────────────────────
function BacktestSection() {
  const [symbol,    setSymbol]    = useState('')
  const [range,     setRange]     = useState<DateRange>('1y')
  const [triggered, setTriggered] = useState(false)
  const [runSymbol, setRunSymbol] = useState('')
  const [runRange,  setRunRange]  = useState<DateRange>('1y')

  const { start, end } = getDateRange(runRange)

  const { data, isLoading, isError, error } = useQuery<ReviewResponse>({
    queryKey: ['quant-ohlcv', runSymbol, runRange],
    queryFn: async () => {
      const res = await fetch(`/api/review/${runSymbol}?start=${start}&end=${end}`)
      if (!res.ok) throw new Error('K线数据获取失败')
      return res.json()
    },
    enabled: triggered && runSymbol !== '',
    staleTime: 5 * 60 * 1000,
  })

  const ohlcv: OhlcvBar[] = data?.ohlcv ?? []

  const handleRun = () => {
    if (!symbol.trim()) return
    setRunSymbol(symbol.trim())
    setRunRange(range)
    setTriggered(true)
  }

  const RANGE_LABELS: { key: DateRange; label: string }[] = [
    { key: '1m', label: '近1月' },
    { key: '3m', label: '近3月' },
    { key: '6m', label: '近6月' },
    { key: '1y', label: '近1年' },
  ]

  return (
    <div className="space-y-4">
      {/* 标题 */}
      <div>
        <h2 className="text-lg font-bold text-white">策略回测</h2>
        <p className="text-xs text-gray-500 mt-0.5">基于历史K线，对比买入持有 / MA金叉 / RSI反转策略</p>
      </div>

      {/* 控制栏 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
        <div className="flex gap-2 items-center flex-wrap">
          <div className="flex-1 min-w-0">
            <StockSearch
              value={symbol}
              onChange={(sym, _name) => setSymbol(sym)}
              placeholder="代码 / 名称 / 拼音缩写，如 600519 / 茅台 / gzmg"
            />
          </div>
          <button
            onClick={handleRun}
            disabled={!symbol.trim()}
            className="text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg px-4 py-2 font-medium transition-colors shrink-0"
          >
            运行回测
          </button>
        </div>

        {/* 日期范围 */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-gray-500">时间范围：</span>
          {RANGE_LABELS.map(r => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${
                range === r.key ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* 结果 */}
      {!triggered && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center space-y-2">
          <div className="text-3xl">📐</div>
          <div className="text-gray-400 font-medium">输入股票代码，选择回测区间，点击「运行回测」</div>
          <div className="text-xs text-gray-600">支持策略：买入持有 / MA5/20 金叉死叉 / RSI 35/65 反转</div>
          <div className="text-xs text-gray-600">初始资金 100 单位，不含手续费，基于历史数据</div>
        </div>
      )}

      {triggered && isLoading && <Spinner label={`正在加载 ${runSymbol} K线数据...`} />}

      {triggered && isError && (
        <div className="bg-red-900/20 border border-red-800 rounded-xl p-4 text-red-400 text-sm">
          {(error as Error).message}
        </div>
      )}

      {triggered && !isLoading && !isError && ohlcv.length > 0 && (
        <div>
          <div className="text-xs text-gray-600 mb-3">
            {runSymbol} · {start} 至 {end} · {ohlcv.length} 个交易日
          </div>
          <StrategyBacktest ohlcv={ohlcv} />
        </div>
      )}

      {triggered && !isLoading && !isError && ohlcv.length === 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center text-gray-600 text-sm">
          未获取到 {runSymbol} 的 K 线数据，请检查股票代码是否正确
        </div>
      )}
    </div>
  )
}

// ── Section 2: 选股因子（概念板块） ──────────────────────────────────────────
function FactorSection() {
  const { data, isLoading, isError, error, refetch } = useQuery<ConceptsResponse>({
    queryKey: ['quant-sector-concepts'],
    queryFn: async () => {
      const res = await fetch('/api/sector/concepts')
      if (!res.ok) throw new Error('概念板块数据获取失败')
      return res.json()
    },
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  })

  // 按 pct_num 降序，取前 30
  const concepts: ConceptItem[] = (data?.concepts ?? [])
    .slice()
    .sort((a, b) => b.pct_num - a.pct_num)
    .slice(0, 30)

  return (
    <div className="space-y-4">
      {/* 标题 */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">选股因子</h2>
          <p className="text-xs text-gray-500 mt-0.5">基于新浪财经概念板块，实时数据</p>
        </div>
        <div className="flex items-center gap-2">
          {data?.updated_at && (
            <span className="text-xs text-gray-600">
              更新 <b className="text-gray-500">{data.updated_at}</b>
            </span>
          )}
          <button
            onClick={() => refetch()}
            className="text-xs text-gray-400 hover:text-white border border-gray-800 rounded-lg px-2.5 py-1.5 transition-colors"
          >
            🔄 刷新
          </button>
        </div>
      </div>

      {isLoading && <Spinner label="加载概念板块..." />}

      {isError && (
        <div className="bg-red-900/20 border border-red-800 rounded-xl p-4 text-red-400 text-sm">
          {(error as Error).message}
        </div>
      )}

      {!isLoading && !isError && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs text-gray-500">
                <th className="text-left px-4 py-3 w-10">排名</th>
                <th className="text-left px-2 py-3">概念名称</th>
                <th className="text-right px-4 py-3">涨跌幅</th>
                <th className="text-left px-4 py-3 hidden sm:table-cell">领涨股</th>
                <th className="text-right px-4 py-3 hidden sm:table-cell">领涨股涨幅</th>
                <th className="text-right px-4 py-3 hidden md:table-cell">成分股数量</th>
              </tr>
            </thead>
            <tbody>
              {concepts.map((c, i) => (
                <tr
                  key={c.code || c.name}
                  className="border-t border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                >
                  <td className="px-4 py-2.5 text-xs text-gray-600 tabular-nums">{i + 1}</td>
                  <td className="px-2 py-2.5 text-gray-300 font-medium">{c.name}</td>
                  <td className={`px-4 py-2.5 text-right font-mono font-semibold tabular-nums ${pctColor(c.pct_num)}`}>
                    {c.pct}
                  </td>
                  <td className="px-4 py-2.5 text-gray-400 text-xs hidden sm:table-cell">
                    {c.leader || '--'}
                  </td>
                  <td className={`px-4 py-2.5 text-right font-mono text-xs tabular-nums hidden sm:table-cell ${pctColor(c.leader_pct)}`}>
                    {c.leader_pct > 0 ? '+' : ''}{c.leader_pct.toFixed(2)}%
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-500 text-xs hidden md:table-cell">
                    {c.company_count} 家
                  </td>
                </tr>
              ))}
              {concepts.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-gray-600 text-sm">
                    暂无概念板块数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────

type QuantTab = 'library' | 'backtest' | 'factor' | 'mine'

export default function QuantPage({ onSelectStock }: Props) {
  const [activeTab, setActiveTab] = useState<QuantTab>('library')

  const TABS: { key: QuantTab; label: string }[] = [
    { key: 'library',  label: '策略仓库' },
    { key: 'backtest', label: '策略对比' },
    { key: 'factor',   label: '选股因子' },
    { key: 'mine',     label: '我的策略' },
  ]

  return (
    <div className="min-h-screen bg-gray-950 px-4 py-8">
      <div className="max-w-5xl mx-auto">

        {/* 大标题 */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white">量化专区</h1>
          <p className="text-sm text-gray-500 mt-1">策略仓库 · 策略对比 · 选股因子 · 我的策略</p>
        </div>

        {/* Tab 切换 */}
        <div className="flex gap-2 mb-6">
          {TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`text-sm px-4 py-2 rounded-lg font-medium transition-colors ${
                activeTab === tab.key
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-white'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* 内容区 */}
        {activeTab === 'library'  && <StrategyLibraryPage onSelectStock={onSelectStock} />}
        {activeTab === 'backtest' && <BacktestSection />}
        {activeTab === 'factor'   && <FactorSection />}
        {activeTab === 'mine'     && <CustomStrategyPage onSelectStock={onSelectStock} />}

      </div>
    </div>
  )
}
