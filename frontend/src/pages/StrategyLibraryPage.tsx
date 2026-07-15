/**
 * 策略仓库页
 * 学习向：展示6种量化策略，支持选择策略后运行回测对比
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import StockSearch from '../components/StockSearch'
import {
  strategyBuyHold,
  strategyMACross,
  strategyRsiReversal,
  strategyBollingerBands,
  strategyMACD,
  strategyBreakout,
} from '../utils/backtest'
import type { OhlcvBar } from '../types'

// ── 类型 ──────────────────────────────────────────────────────────────────────

interface ReviewResponse {
  ohlcv: OhlcvBar[]
  [key: string]: unknown
}

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
}

type DateRange = '3m' | '6m' | '1y'

// ── 策略元数据 ────────────────────────────────────────────────────────────────

type StrategyMeta = {
  id: string
  name: string
  emoji: string
  tagline: string
  type: string
  typeColor: string
  risk: string
  riskColor: string
  conditions: string
  signals: string[]
  logic: string
  pros: string[]
  cons: string[]
  params: never[]
  fn: string
}

const STRATEGIES: StrategyMeta[] = [
  {
    id: 'buy_hold',
    name: '买入持有',
    emoji: '🏦',
    tagline: '最简单的策略：买了就不动',
    type: '基准',
    typeColor: 'bg-gray-700 text-gray-300',
    risk: '中',
    riskColor: 'text-yellow-400',
    conditions: '长期牛市',
    signals: ['第一天开盘价买入', '最后一天收盘价卖出'],
    logic: '不择时，全程持仓。作为其他策略的对比基准，如果你的策略跑不赢买入持有，说明策略没有价值。',
    pros: ['无需盯盘', '交易成本极低', '适合长期持有优质股'],
    cons: ['熊市会吃满所有下跌', '没有止损保护'],
    params: [],
    fn: 'buyHold',
  },
  {
    id: 'ma_cross',
    name: 'MA均线金叉',
    emoji: '📈',
    tagline: '短线穿越长线时追涨，反向时离场',
    type: '趋势',
    typeColor: 'bg-blue-900/60 text-blue-300',
    risk: '中',
    riskColor: 'text-yellow-400',
    conditions: '单边趋势市场',
    signals: ['MA5 上穿 MA20 → 买入', 'MA5 下穿 MA20 → 卖出'],
    logic: 'MA（移动平均线）平滑价格波动。短期均线（5日）反映近期趋势，长期均线（20日）反映中期趋势。短线从下往上穿越长线（金叉）说明趋势变强，是买入信号；反之（死叉）是卖出信号。',
    pros: ['顺势交易', '能抓住中长期趋势', '逻辑简单易理解'],
    cons: ['震荡市频繁假信号', '信号有滞后性，追高风险'],
    params: [],
    fn: 'maCross',
  },
  {
    id: 'rsi',
    name: 'RSI低吸高抛',
    emoji: '🔄',
    tagline: '超跌时买入，超涨时卖出',
    type: '反转',
    typeColor: 'bg-emerald-900/60 text-emerald-300',
    risk: '中',
    riskColor: 'text-yellow-400',
    conditions: '震荡市场',
    signals: ['RSI < 35 → 超跌买入', 'RSI > 65 → 超涨卖出'],
    logic: 'RSI（相对强弱指数）衡量一段时间内涨跌幅的比例，范围0-100。低于30超卖（可能反弹），高于70超买（可能回落）。这个策略逆势操作，在大家恐慌抛售时买入，在大家贪婪追涨时卖出。',
    pros: ['震荡市效果好', '有清晰的进出场规则'],
    cons: ['趋势市容易被扫损', '强势股RSI长期偏高不会触发卖出'],
    params: [],
    fn: 'rsi',
  },
  {
    id: 'bollinger',
    name: '布林带策略',
    emoji: '📊',
    tagline: '价格触碰通道边界时操作',
    type: '反转',
    typeColor: 'bg-emerald-900/60 text-emerald-300',
    risk: '中高',
    riskColor: 'text-orange-400',
    conditions: '震荡 / 区间市',
    signals: ['收盘价 跌破 下轨 → 买入', '收盘价 突破 上轨 → 卖出'],
    logic: '布林带由中轨（20日均线）±2倍标准差构成。价格约有95%的时间在布林带内运动。当价格触碰下轨，说明近期下跌幅度异常，统计上可能均值回归；触碰上轨则相反。布林带会随波动率自动收窄或扩张。',
    pros: ['自适应波动率', '区间市效果稳定', '信号明确直观'],
    cons: ['趋势突破时会连续止损', '参数敏感'],
    params: [],
    fn: 'bollinger',
  },
  {
    id: 'macd',
    name: 'MACD金叉',
    emoji: '⚡',
    tagline: '动量加速时买入，动量减弱时离场',
    type: '趋势',
    typeColor: 'bg-blue-900/60 text-blue-300',
    risk: '中',
    riskColor: 'text-yellow-400',
    conditions: '趋势延续市场',
    signals: ['MACD柱从负转正（快线上穿慢线）→ 买入', 'MACD柱从正转负（快线下穿慢线）→ 卖出'],
    logic: 'MACD用快速EMA(12)减慢速EMA(26)得到差值（DIF），再对差值做EMA(9)得到信号线（DEA）。两线之差就是柱状图。柱子由负转正说明上涨动量超过下跌动量，是买入时机。EMA比SMA对近期价格更敏感，信号更快。',
    pros: ['兼顾趋势和动量', '被广泛使用和验证', '适合中短线操作'],
    cons: ['也有滞后性', '震荡市假信号多'],
    params: [],
    fn: 'macd',
  },
  {
    id: 'breakout',
    name: '价格突破',
    emoji: '🚀',
    tagline: '创新高时追涨，创新低时止损',
    type: '动量',
    typeColor: 'bg-purple-900/60 text-purple-300',
    risk: '高',
    riskColor: 'text-red-400',
    conditions: '强势上涨市场',
    signals: ['收盘价 > 近20日最高价 → 买入', '收盘价 < 近20日最低价 → 卖出'],
    logic: '海龟交易法则的核心思想：突破N日高点说明多头力量强大，趋势可能持续，应该追涨；跌破N日低点则反之止损离场。这个策略违反"高买低卖的直觉"，但在强趋势市场中非常有效。风险在于震荡时频繁被打出。',
    pros: ['在强势股上收益极高', '顺势不逆势', '止损纪律明确'],
    cons: ['震荡市磨损大', '买点往往已经涨了一段', '心理上难以执行'],
    params: [],
    fn: 'breakout',
  },
]

// ── 日期工具 ──────────────────────────────────────────────────────────────────

function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}${m}${day}`
}

function getDateRange(range: DateRange): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  if (range === '3m') start.setMonth(start.getMonth() - 3)
  else if (range === '6m') start.setMonth(start.getMonth() - 6)
  else start.setFullYear(start.getFullYear() - 1)
  return { start: toDateStr(start), end: toDateStr(end) }
}

// ── 策略函数映射 ──────────────────────────────────────────────────────────────

function runStrategyFn(fn: string, ohlcv: OhlcvBar[]) {
  switch (fn) {
    case 'buyHold':   return strategyBuyHold(ohlcv)
    case 'maCross':   return strategyMACross(ohlcv)
    case 'rsi':       return strategyRsiReversal(ohlcv)
    case 'bollinger': return strategyBollingerBands(ohlcv)
    case 'macd':      return strategyMACD(ohlcv)
    case 'breakout':  return strategyBreakout(ohlcv)
    default:          return strategyBuyHold(ohlcv)
  }
}

// ── 子组件 ────────────────────────────────────────────────────────────────────

function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-32 text-gray-500">
      <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mr-2" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

function StatCell({
  label, value, sub, highlight,
}: {
  label: string
  value: string
  sub?: string
  highlight?: 'good' | 'bad' | 'neutral'
}) {
  const color =
    highlight === 'good' ? 'text-red-400' :
    highlight === 'bad'  ? 'text-emerald-400' :
    'text-gray-200'
  return (
    <div className="bg-gray-800/60 rounded-lg p-3 text-center">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-base font-bold tabular-nums ${color}`}>{value}</div>
      {sub && <div className="text-xs text-gray-600 mt-0.5">{sub}</div>}
    </div>
  )
}

// ── 策略卡片 ──────────────────────────────────────────────────────────────────

function StrategyCard({
  meta,
  selected,
  onClick,
}: {
  meta: StrategyMeta
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left bg-gray-900 border rounded-xl p-4 transition-all hover:border-blue-500/60 hover:bg-gray-900/80 space-y-2 ${
        selected
          ? 'border-blue-500 ring-1 ring-blue-500/40 bg-gray-900'
          : 'border-gray-800'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{meta.emoji}</span>
          <div>
            <div className="font-bold text-white text-sm leading-tight">{meta.name}</div>
            <span className={`inline-block text-xs px-1.5 py-0.5 rounded mt-0.5 ${meta.typeColor}`}>
              {meta.type}
            </span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-xs text-gray-500">风险</div>
          <div className={`text-sm font-semibold ${meta.riskColor}`}>{meta.risk}</div>
        </div>
      </div>

      {/* Tagline */}
      <p className="text-xs text-gray-400 leading-relaxed">{meta.tagline}</p>

      {/* Conditions */}
      <div className="text-xs text-gray-600">
        <span className="text-gray-500">适合：</span>{meta.conditions}
      </div>
    </button>
  )
}

// ── 详情面板 ──────────────────────────────────────────────────────────────────

function DetailPanel({ meta, ohlcv }: { meta: StrategyMeta; ohlcv: OhlcvBar[] }) {
  const { selected, baseline } = useMemo(() => {
    if (!ohlcv || ohlcv.length < 5) return { selected: null, baseline: null }
    return {
      selected: runStrategyFn(meta.fn, ohlcv),
      baseline: strategyBuyHold(ohlcv),
    }
  }, [meta.fn, ohlcv])

  // 合并权益曲线
  const chartData = useMemo(() => {
    if (!selected || !baseline) return []
    return selected.equity.map((pt, i) => ({
      date: pt.date.slice(5),
      策略: pt.value,
      买入持有: baseline.equity[i]?.value ?? 100,
    }))
  }, [selected, baseline])

  // x轴采样
  const ticks = useMemo(() => {
    if (!chartData.length) return []
    const step = Math.max(1, Math.floor(chartData.length / 8))
    return chartData
      .filter((_, i) => i % step === 0 || i === chartData.length - 1)
      .map(d => d.date)
  }, [chartData])

  const TICK_STYLE = { fill: '#6b7280', fontSize: 10 }

  const retDiff = selected && baseline
    ? parseFloat((selected.totalReturn - baseline.totalReturn).toFixed(2))
    : 0

  return (
    <div className="mt-6 space-y-4">
      {/* 策略说明卡 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-3">
          <span className="text-3xl">{meta.emoji}</span>
          <div>
            <h3 className="text-lg font-bold text-white">{meta.name}</h3>
            <p className="text-sm text-gray-400">{meta.tagline}</p>
          </div>
        </div>

        {/* 逻辑说明 */}
        <div>
          <div className="text-xs text-gray-500 mb-1 uppercase tracking-wider">策略逻辑</div>
          <p className="text-sm text-gray-300 leading-relaxed">{meta.logic}</p>
        </div>

        {/* 信号规则 */}
        <div>
          <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider">交易信号</div>
          <div className="flex flex-wrap gap-2">
            {meta.signals.map((s, i) => (
              <span
                key={i}
                className={`text-xs px-2.5 py-1 rounded-full border ${
                  s.includes('买入')
                    ? 'bg-red-900/30 border-red-800/60 text-red-300'
                    : 'bg-emerald-900/30 border-emerald-800/60 text-emerald-300'
                }`}
              >
                {s}
              </span>
            ))}
          </div>
        </div>

        {/* 优缺点 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider">优点</div>
            <ul className="space-y-1">
              {meta.pros.map((p, i) => (
                <li key={i} className="text-xs text-gray-300 flex items-start gap-1.5">
                  <span className="text-red-400 mt-0.5 shrink-0">✓</span>
                  {p}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider">缺点</div>
            <ul className="space-y-1">
              {meta.cons.map((c, i) => (
                <li key={i} className="text-xs text-gray-300 flex items-start gap-1.5">
                  <span className="text-emerald-400 mt-0.5 shrink-0">✗</span>
                  {c}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      {/* 回测结果 */}
      {selected && baseline && chartData.length > 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-300">回测结果对比</span>
            <span className="text-xs text-gray-600">初始资金 100 单位，不含手续费</span>
          </div>

          {/* 权益曲线 */}
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="date" ticks={ticks} tick={TICK_STYLE} />
              <YAxis tick={TICK_STYLE} domain={['auto', 'auto']} />
              <Tooltip
                contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#9ca3af' }}
                // @ts-expect-error recharts ValueType includes undefined but we control data
              formatter={(v: number, name: string) => [
                  `${v > 100 ? '+' : ''}${(v - 100).toFixed(2)}%`,
                  name,
                ]}
              />
              <Line
                type="monotone"
                dataKey="策略"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 3 }}
              />
              <Line
                type="monotone"
                dataKey="买入持有"
                stroke="#6b7280"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                activeDot={{ r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>

          {/* 图例 */}
          <div className="flex items-center gap-4 text-xs text-gray-500">
            <span className="flex items-center gap-1.5">
              <span className="w-5 h-0.5 bg-blue-500 inline-block" />
              {meta.name}（本策略）
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-5 h-0.5 bg-gray-500 inline-block border-dashed border-t" style={{ borderTop: '2px dashed #6b7280', background: 'none' }} />
              买入持有（基准）
            </span>
          </div>

          {/* 统计指标 */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <StatCell
              label="策略总收益"
              value={`${selected.totalReturn > 0 ? '+' : ''}${selected.totalReturn}%`}
              highlight={selected.totalReturn > 0 ? 'good' : selected.totalReturn < 0 ? 'bad' : 'neutral'}
            />
            <StatCell
              label="最大回撤"
              value={`${selected.maxDrawdown}%`}
              highlight={selected.maxDrawdown < -15 ? 'bad' : 'neutral'}
            />
            <StatCell
              label="胜率"
              value={selected.winRate > 0 ? `${selected.winRate}%` : '--'}
            />
            <StatCell
              label="交易次数"
              value={String(selected.trades)}
            />
            <StatCell
              label="Sharpe比率"
              value={String(selected.sharpe)}
              sub="年化，无风险2.5%"
            />
            <StatCell
              label="vs 买入持有"
              value={`${retDiff > 0 ? '+' : ''}${retDiff}%`}
              sub={`基准 ${baseline.totalReturn > 0 ? '+' : ''}${baseline.totalReturn}%`}
              highlight={retDiff > 0 ? 'good' : retDiff < 0 ? 'bad' : 'neutral'}
            />
          </div>

          <p className="text-xs text-gray-700">
            ⚠ 回测基于历史数据，不代表未来收益。仅供学习参考。
          </p>
        </div>
      ) : (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center text-gray-600 text-sm">
          数据不足，无法运行回测（至少需要30个交易日）
        </div>
      )}
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────────────────────────────

export default function StrategyLibraryPage({ onSelectStock: _onSelectStock }: Props) {
  const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(null)
  const [symbol, setSymbol] = useState('')
  const [runSymbol, setRunSymbol] = useState('')
  const [dateRange, setDateRange] = useState<DateRange>('1y')
  const [hasRun, setHasRun] = useState(false)

  const { start, end } = getDateRange(dateRange)

  const { data, isLoading, isError, error } = useQuery<ReviewResponse>({
    queryKey: ['strategy-lib-ohlcv', runSymbol, dateRange],
    queryFn: async () => {
      const res = await fetch(`/api/review/${runSymbol}?start=${start}&end=${end}`)
      if (!res.ok) throw new Error('K线数据获取失败')
      return res.json()
    },
    enabled: hasRun && runSymbol !== '',
    staleTime: 5 * 60 * 1000,
  })

  const ohlcv: OhlcvBar[] = data?.ohlcv ?? []

  const handleRun = () => {
    if (!symbol.trim()) return
    setRunSymbol(symbol.trim())
    setHasRun(true)
  }

  const selectedMeta = STRATEGIES.find(s => s.id === selectedStrategyId) ?? null

  const DATE_RANGE_LABELS: { key: DateRange; label: string }[] = [
    { key: '3m', label: '近3月' },
    { key: '6m', label: '近6月' },
    { key: '1y', label: '近1年' },
  ]

  return (
    <div className="space-y-6">
      {/* 输入栏 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3 sticky top-0 z-10">
        <div className="flex gap-2 items-start flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <StockSearch
              value={symbol}
              onChange={(sym, _name) => setSymbol(sym)}
              placeholder="代码 / 名称 / 拼音缩写，如 600519 / 茅台 / gzmg"
            />
          </div>
          <div className="flex gap-1.5">
            {DATE_RANGE_LABELS.map(r => (
              <button
                key={r.key}
                onClick={() => setDateRange(r.key)}
                className={`text-xs px-3 py-2 rounded-lg transition-colors ${
                  dateRange === r.key
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:text-white'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
          <button
            onClick={handleRun}
            disabled={!symbol.trim()}
            className="text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg px-4 py-2 font-medium transition-colors"
          >
            运行
          </button>
        </div>
        {hasRun && runSymbol && (
          <div className="text-xs text-gray-600">
            {isLoading
              ? `正在加载 ${runSymbol}...`
              : isError
              ? `加载失败：${(error as Error).message}`
              : `${runSymbol} · ${ohlcv.length} 个交易日`}
          </div>
        )}
      </div>

      {/* 策略网格 */}
      <div>
        <div className="text-xs text-gray-500 mb-3">点击策略卡片查看详细说明和回测结果</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {STRATEGIES.map(meta => (
            <StrategyCard
              key={meta.id}
              meta={meta}
              selected={selectedStrategyId === meta.id}
              onClick={() =>
                setSelectedStrategyId(prev => (prev === meta.id ? null : meta.id))
              }
            />
          ))}
        </div>
      </div>

      {/* 详情区 */}
      {selectedMeta && !hasRun && (
        <div className="bg-gray-900 border border-blue-900/40 rounded-xl p-6 text-center space-y-2">
          <div className="text-2xl">{selectedMeta.emoji}</div>
          <div className="text-gray-300 font-medium">
            已选择「{selectedMeta.name}」策略
          </div>
          <div className="text-sm text-gray-500">
            输入股票代码，点击「运行」查看回测效果
          </div>
        </div>
      )}

      {selectedMeta && hasRun && isLoading && (
        <Spinner label={`正在加载 ${runSymbol} K线数据...`} />
      )}

      {selectedMeta && hasRun && isError && (
        <div className="bg-red-900/20 border border-red-800 rounded-xl p-4 text-red-400 text-sm">
          {(error as Error).message}
        </div>
      )}

      {selectedMeta && hasRun && !isLoading && !isError && (
        <DetailPanel meta={selectedMeta} ohlcv={ohlcv} />
      )}
    </div>
  )
}
