/**
 * 选股器页面
 * 功能：按行业展示综合评分，多维度因子排序选股
 * 数据来源：akshare 同花顺行业数据（已在复盘接口里采集）
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from 'recharts'

// ── 行业数据类型 ──────────────────────────────────────────────────────
interface IndustryItem {
  name: string
  pct: string         // 涨跌幅字符串如 "+1.23%"
  net_in?: string
  up_count?: string
  down_count?: string
  leader?: string
  rank?: number
  total?: number
  pct_num?: number    // 解析后的数字
}

interface SummaryResponse {
  industries: IndustryItem[]
  updated_at: string
}

// ── 从后端获取行业汇总 ────────────────────────────────────────────────
async function fetchIndustrySummary(): Promise<SummaryResponse> {
  const res = await fetch('/api/industry/summary')
  if (!res.ok) throw new Error('行业数据获取失败')
  return res.json()
}

// ── 颜色工具 ──────────────────────────────────────────────────────────
function pctColor(v: number) {
  if (v > 2)  return 'text-red-400'
  if (v > 0)  return 'text-red-300'
  if (v < -2) return 'text-emerald-400'
  if (v < 0)  return 'text-emerald-300'
  return 'text-gray-400'
}

function barColor(v: number) {
  if (v > 1.5) return '#ef4444'
  if (v > 0)   return '#f87171'
  if (v < -1.5) return '#22c55e'
  return '#4ade80'
}

// ── 页面主体 ──────────────────────────────────────────────────────────
export default function ScreenerPage() {
  const [sortBy, setSortBy] = useState<'pct' | 'name' | 'up'>('pct')
  const [filter, setFilter] = useState('')

  const { data: summaryData, isLoading, error, refetch } = useQuery<SummaryResponse>({
    queryKey: ['industry-summary'],
    queryFn: fetchIndustrySummary,
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
    retry: 1,
  })
  const industries = summaryData?.industries ?? []
  const updatedAt = summaryData?.updated_at ?? ''

  // 解析涨跌幅数字 + 排序
  const sorted = useMemo(() => {
    const parsed = industries.map(it => ({
      ...it,
      pct_num: parseFloat(String(it.pct).replace('%', '').replace('+', '')) || 0,
    }))
    const filtered = filter
      ? parsed.filter(it => it.name.includes(filter))
      : parsed
    return [...filtered].sort((a, b) => {
      if (sortBy === 'pct') return (b.pct_num ?? 0) - (a.pct_num ?? 0)
      if (sortBy === 'up')  return parseInt(String(b.up_count ?? 0)) - parseInt(String(a.up_count ?? 0))
      return a.name.localeCompare(b.name)
    })
  }, [industries, sortBy, filter])

  // Top10 涨幅行业（用于图表）
  const top10 = useMemo(
    () => [...sorted].slice(0, 10),
    [sorted]
  )

  return (
    <div className="min-h-screen bg-gray-950 px-4 py-8">
      <div className="max-w-5xl mx-auto space-y-6">

        {/* 标题 */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">行业选股器</h1>
            <p className="text-sm text-gray-500 mt-1">同花顺 90 行业分类 · 每分钟更新</p>
          </div>
          <div className="flex items-center gap-3">
            {updatedAt && (
              <span className="text-xs text-gray-600">数据更新 <b className="text-gray-500">{updatedAt}</b></span>
            )}
            <button
              onClick={() => refetch()}
              className="text-xs text-gray-400 hover:text-white border border-gray-700 rounded-lg px-3 py-1.5 transition-colors"
            >
              🔄 刷新
            </button>
          </div>
        </div>

        {isLoading && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-gray-400 text-sm">正在加载行业数据...</p>
          </div>
        )}

        {error && (
          <div className="bg-red-900/20 border border-red-800 rounded-xl p-4 text-red-400 text-sm">
            {(error as Error).message} — 请确保后端已启动并已配置 akshare
          </div>
        )}

        {!isLoading && sorted.length > 0 && (
          <>
            {/* 行业涨跌幅条形图（Top10）*/}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <h3 className="text-sm font-medium text-gray-400 mb-4">今日行业涨跌幅 Top 10</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={top10}
                  layout="vertical"
                  margin={{ top: 0, right: 40, bottom: 0, left: 60 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" horizontal={false} />
                  <XAxis
                    type="number"
                    tick={{ fill: '#6b7280', fontSize: 10 }}
                    tickFormatter={v => `${v}%`}
                  />
                  <YAxis
                    dataKey="name"
                    type="category"
                    tick={{ fill: '#9ca3af', fontSize: 10 }}
                    width={58}
                  />
                  <Tooltip
                    contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [`${v > 0 ? '+' : ''}${v}%`, '涨跌幅']}
                  />
                  <Bar dataKey="pct_num" radius={[0, 3, 3, 0]}>
                    {top10.map((it, i) => (
                      <Cell key={i} fill={barColor(it.pct_num ?? 0)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* 筛选 + 排序控制 */}
            <div className="flex gap-3 items-center flex-wrap">
              <input
                type="text"
                placeholder="搜索行业名称..."
                value={filter}
                onChange={e => setFilter(e.target.value)}
                className="flex-1 min-w-0 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-300 placeholder-gray-600 outline-none focus:border-blue-500"
              />
              <div className="flex gap-1.5">
                {([['pct', '按涨幅'], ['up', '按上涨家数'], ['name', '按名称']] as const).map(([k, label]) => (
                  <button
                    key={k}
                    onClick={() => setSortBy(k)}
                    className={`text-xs px-2.5 py-1.5 rounded-lg transition-colors ${
                      sortBy === k ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <span className="text-xs text-gray-600">{sorted.length} 个行业</span>
            </div>

            {/* 行业列表 */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-xs text-gray-500">
                    <th className="text-left px-4 py-3">行业</th>
                    <th className="text-right px-4 py-3">涨跌幅</th>
                    <th className="text-right px-4 py-3 hidden sm:table-cell">上涨家数</th>
                    <th className="text-right px-4 py-3 hidden sm:table-cell">下跌家数</th>
                    <th className="text-right px-4 py-3 hidden md:table-cell">净流入</th>
                    <th className="text-right px-4 py-3">领涨股</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((it, i) => (
                    <tr
                      key={it.name}
                      className="border-t border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                    >
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-600 w-5 tabular-nums">{i + 1}</span>
                          <span className="text-gray-300">{it.name}</span>
                        </div>
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono font-semibold tabular-nums ${pctColor(it.pct_num ?? 0)}`}>
                        {it.pct ?? '--'}
                      </td>
                      <td className="px-4 py-2.5 text-right text-red-400 text-xs hidden sm:table-cell">
                        {it.up_count ?? '--'}
                      </td>
                      <td className="px-4 py-2.5 text-right text-emerald-400 text-xs hidden sm:table-cell">
                        {it.down_count ?? '--'}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-500 text-xs hidden md:table-cell">
                        {it.net_in ?? '--'}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-400 text-xs">
                        {it.leader ?? '--'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
