/**
 * 龙虎榜页 — 近N日上榜统计 + 当日明细
 * 数据来源：新浪财经龙虎榜（akshare）
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import WatchlistButton from '../components/WatchlistButton'

// ── 类型 ──────────────────────────────────────────────────────────────────────
interface LhbStock {
  symbol:      string
  name:        string
  count:       number
  buy_amount:  number
  sell_amount: number
  net_amount:  number
  buy_seats:   number
  sell_seats:  number
}

interface TopResponse {
  stocks:     LhbStock[]
  days:       number
  updated_at: string
  amount_unit: string
  source:     string
}

interface LhbEntry {
  symbol:    string
  name:      string
  price:     number
  volume:    number
  amount:    number
  reason:    string
}

interface DailyResponse {
  entries:    LhbEntry[]
  date:       string
  updated_at: string
  amount_unit: string
  source:     string
  sort_by:    string
  is_published: boolean
  message:    string
}

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
}

// ── 工具 ──────────────────────────────────────────────────────────────────────
function netColor(v: number): string {
  if (v > 0) return 'text-red-400'
  if (v < 0) return 'text-emerald-400'
  return 'text-gray-400'
}

function latestPublishedTradingDay(): string {
  const d = new Date()
  if (d.getDay() >= 1 && d.getDay() <= 5 && d.getHours() < 16) {
    d.setDate(d.getDate() - 1)
  }
  while (d.getDay() === 0 || d.getDay() === 6) {
    d.setDate(d.getDate() - 1)
  }
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}${m}${day}`
}

// ── 加载中 ───────────────────────────────────────────────────────────────────
function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-48 text-gray-500">
      <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mr-2" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

// ── 错误提示 ─────────────────────────────────────────────────────────────────
function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="bg-red-900/20 border border-red-800 rounded-xl p-4 text-red-400 text-sm">
      {msg}
    </div>
  )
}

// ── 近N日上榜视图 ──────────────────────────────────────────────────────────────
function TopView({
  days,
  onSelectStock,
}: {
  days: number
  onSelectStock?: (symbol: string, name: string) => void
}) {
  const { data, isLoading, isError, error, refetch } = useQuery<TopResponse>({
    queryKey: ['lhb-top', days],
    queryFn: async () => {
      const res = await fetch(`/api/lhb/top?days=${days}`)
      if (!res.ok) throw new Error('龙虎榜数据获取失败')
      return res.json()
    },
    staleTime: 5 * 60 * 1000,
  })

  const stocks = data?.stocks ?? []
  // 按净额降序排列（后端已排序，前端再保证）
  const sorted = [...stocks].sort((a, b) => b.net_amount - a.net_amount)

  return (
    <div>
      {/* 控制栏 */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">
          {data ? `共 ${sorted.length} 只上榜股票，金额单位：${data.amount_unit}` : ''}
        </p>
        <div className="flex items-center gap-3">
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

      {isLoading && <Spinner label="加载龙虎榜数据..." />}
      {isError && <ErrorBox msg={(error as Error).message} />}

      {!isLoading && !isError && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs text-gray-500">
                <th className="text-left px-4 py-3 w-10">#</th>
                <th className="text-left px-2 py-3">股票</th>
                <th className="text-right px-4 py-3">上榜次数</th>
                <th className="text-right px-4 py-3">净额(亿)</th>
                <th className="text-right px-4 py-3 hidden md:table-cell">累积买入(亿)</th>
                <th className="text-right px-4 py-3 hidden md:table-cell">累积卖出(亿)</th>
                <th className="text-right px-4 py-3 hidden sm:table-cell">买入席位</th>
                <th className="text-right px-4 py-3 hidden sm:table-cell">卖出席位</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s, i) => (
                <tr
                  key={s.symbol}
                  className="border-t border-gray-800/50 hover:bg-gray-800/30 transition-colors cursor-pointer group"
                  onClick={() => onSelectStock?.(s.symbol, s.name)}
                >
                  <td className="px-4 py-2.5 text-xs text-gray-600 tabular-nums">{i + 1}</td>
                  <td className="px-2 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <WatchlistButton code={s.symbol} name={s.name} />
                      <div>
                        <div className="font-medium text-gray-200 group-hover:text-white transition-colors">
                          {s.name}
                        </div>
                        <div className="text-xs text-gray-600">{s.symbol}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-300 tabular-nums">{s.count}</td>
                  <td className={`px-4 py-2.5 text-right font-mono font-semibold tabular-nums ${netColor(s.net_amount)}`}>
                    {s.net_amount > 0 ? '+' : ''}{s.net_amount.toFixed(2)}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-400 font-mono tabular-nums hidden md:table-cell">
                    {s.buy_amount.toFixed(2)}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-400 font-mono tabular-nums hidden md:table-cell">
                    {s.sell_amount.toFixed(2)}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-500 text-xs hidden sm:table-cell">
                    {s.buy_seats}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-500 text-xs hidden sm:table-cell">
                    {s.sell_seats}
                  </td>
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center py-12 text-gray-600 text-sm">
                    暂无龙虎榜数据
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

// ── 当日明细视图 ──────────────────────────────────────────────────────────────
function DailyView({
  onSelectStock,
}: {
  onSelectStock?: (symbol: string, name: string) => void
}) {
  const [date, setDate] = useState<string>(latestPublishedTradingDay())
  const [queryDate, setQueryDate] = useState<string>(latestPublishedTradingDay())

  const { data, isLoading, isError, error, refetch } = useQuery<DailyResponse>({
    queryKey: ['lhb-daily', queryDate],
    queryFn: async () => {
      const res = await fetch(`/api/lhb/daily?date=${queryDate}`)
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        throw new Error(body?.detail || '龙虎榜日报数据获取失败')
      }
      return res.json()
    },
    staleTime: 5 * 60 * 1000,
  })

  const entries = data?.entries ?? []

  return (
    <div>
      {/* 控制栏 */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">日期</label>
          <input
            type="text"
            value={date}
            onChange={e => setDate(e.target.value)}
            placeholder="YYYYMMDD"
            maxLength={8}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-300 placeholder-gray-600 outline-none focus:border-blue-500 w-32 font-mono"
          />
          <button
            onClick={() => setQueryDate(date)}
            className="text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-3 py-1.5 transition-colors"
          >
            查询
          </button>
        </div>
        <div className="flex-1" />
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

      {isLoading && <Spinner label="加载龙虎榜日报..." />}
      {isError && <ErrorBox msg={(error as Error).message} />}

      {!isLoading && !isError && (
        <>
          {data && (
            <p className="text-xs text-gray-600 mb-3">
              {data.date} — 共 {entries.length} 条记录，金额单位：{data.amount_unit}，默认按成交额从高到低
            </p>
          )}
          {data?.message && (
            <div className="mb-3 rounded-lg border border-amber-800/70 bg-amber-950/20 px-4 py-3 text-sm text-amber-300">
              {data.message}
            </div>
          )}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-xs text-gray-500">
                  <th className="text-left px-4 py-3">股票</th>
                  <th className="text-right px-4 py-3">收盘价</th>
                  <th className="text-right px-4 py-3 hidden sm:table-cell">成交额(亿)</th>
                  <th className="text-left px-4 py-3">上榜原因</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e, i) => (
                  <tr
                    key={`${e.symbol}-${i}`}
                    className="border-t border-gray-800/50 hover:bg-gray-800/30 transition-colors cursor-pointer group"
                    onClick={() => onSelectStock?.(e.symbol, e.name)}
                  >
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <WatchlistButton code={e.symbol} name={e.name} />
                        <div>
                          <div className="font-medium text-gray-200 group-hover:text-white transition-colors">
                            {e.name}
                          </div>
                          <div className="text-xs text-gray-600">{e.symbol}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono tabular-nums text-gray-300">
                      {e.price > 0 ? `¥${e.price.toFixed(2)}` : '--'}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-400 font-mono tabular-nums hidden sm:table-cell">
                      {e.amount.toFixed(2)}
                    </td>
                    <td className="px-4 py-2.5 text-gray-400 text-xs max-w-[200px]">
                      {e.reason.length > 20 ? (
                        <span title={e.reason} className="cursor-help underline decoration-dotted">
                          {e.reason.slice(0, 20)}…
                        </span>
                      ) : (
                        e.reason || '--'
                      )}
                    </td>
                  </tr>
                ))}
                {entries.length === 0 && (
                  <tr>
                    <td colSpan={4} className="text-center py-12 text-gray-600 text-sm">
                      {data?.message || '该日期暂无龙虎榜数据'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────
export default function LhbPage({ onSelectStock }: Props) {
  const [view, setView] = useState<'top' | 'daily'>('top')
  const [days, setDays] = useState<number>(5)

  const DAY_OPTIONS = [5, 10, 30, 60] as const

  return (
    <div className="min-h-screen bg-gray-950 px-4 py-8">
      <div className="max-w-6xl mx-auto space-y-6">

        {/* 标题 */}
        <div>
          <h1 className="text-2xl font-bold text-white">龙虎榜</h1>
          <p className="text-sm text-gray-500 mt-1">新浪财经 / 东方财富（AkShare）汇总，金额统一为亿元，缓存 5 分钟</p>
        </div>

        {/* Tab 切换 */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* 近N日 */}
          <button
            onClick={() => setView('top')}
            className={`text-sm px-4 py-1.5 rounded-lg font-medium transition-colors ${
              view === 'top' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
            }`}
          >
            近N日上榜
          </button>

          {/* 当日明细 */}
          <button
            onClick={() => setView('daily')}
            className={`text-sm px-4 py-1.5 rounded-lg font-medium transition-colors ${
              view === 'daily' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
            }`}
          >
            当日明细
          </button>

          {/* 天数选择（仅在 top 视图显示） */}
          {view === 'top' && (
            <>
              <div className="w-px h-5 bg-gray-700 mx-1" />
              {DAY_OPTIONS.map(d => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${
                    days === d ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
                  }`}
                >
                  近 {d} 日
                </button>
              ))}
            </>
          )}
        </div>

        {/* 内容 */}
        {view === 'top' ? (
          <TopView days={days} onSelectStock={onSelectStock} />
        ) : (
          <DailyView onSelectStock={onSelectStock} />
        )}

      </div>
    </div>
  )
}
