import { useCallback, useEffect, useState } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  Landmark,
  MessageCircleQuestion,
  RefreshCw,
} from 'lucide-react'
import { aiAssistantStore } from '../stores/aiAssistantStore'

interface StockCapitalRow {
  rank: number
  symbol: string
  name: string
  price?: number | null
  pct_change?: number | null
  turnover_rate?: number | null
  net_amount_yi: number
  turnover_yi?: number | null
  net_ratio?: number | null
}

interface StockCapitalData {
  inflow?: StockCapitalRow[]
  outflow?: StockCapitalRow[]
  updated_at?: string
  refresh_seconds?: number
  source?: string
  note?: string
  stale?: boolean
  error?: string
}

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
}

function pctClass(value?: number | null) {
  return Number(value || 0) > 0 ? 'text-red-400' : Number(value || 0) < 0 ? 'text-emerald-400' : 'text-gray-400'
}

function percent(value?: number | null) {
  if (value === null || value === undefined) return '--'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function money(value: number) {
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}亿`
}

function RankingColumn({
  title,
  rows,
  direction,
  onSelectStock,
}: {
  title: string
  rows: StockCapitalRow[]
  direction: 'inflow' | 'outflow'
  onSelectStock?: Props['onSelectStock']
}) {
  const Icon = direction === 'inflow' ? ArrowUpRight : ArrowDownRight
  const titleColor = direction === 'inflow' ? 'text-red-300' : 'text-emerald-300'

  return (
    <div className="bg-gray-900">
      <div className={`flex items-center gap-2 border-b border-gray-800 px-4 py-2.5 text-xs font-medium ${titleColor}`}>
        <Icon className="h-4 w-4" />{title}
        <span className="ml-auto grid w-[270px] grid-cols-[72px_100px_74px] text-right font-normal text-gray-600">
          <span>涨跌</span><span>资金净额</span><span>换手率</span>
        </span>
      </div>
      {rows.length ? (
        <div className="divide-y divide-gray-800">
          {rows.slice(0, 10).map(row => (
            <div key={`${direction}-${row.symbol}`} className="flex items-center px-3 hover:bg-gray-800/50">
              <button
                type="button"
                onClick={() => onSelectStock?.(row.symbol, row.name)}
                className="grid min-w-0 flex-1 grid-cols-[28px_minmax(0,1fr)_72px_100px_74px] items-center gap-2 py-2.5 text-left"
                title={`查看${row.name}`}
              >
                <span className="text-xs text-gray-600">{String(row.rank).padStart(2, '0')}</span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-gray-200">{row.name}</span>
                  <span className="block text-xs text-gray-600">{row.symbol} · ¥{row.price?.toFixed(2) ?? '--'}</span>
                </span>
                <span className={`text-right text-sm ${pctClass(row.pct_change)}`}>{percent(row.pct_change)}</span>
                <span className={`text-right text-sm font-medium ${pctClass(row.net_amount_yi)}`}>{money(row.net_amount_yi)}</span>
                <span className="text-right text-xs text-gray-400">{percent(row.turnover_rate)}</span>
              </button>
              <button
                type="button"
                title={`向AI询问${row.name}的资金流`}
                aria-label={`向AI询问${row.name}的资金流`}
                onClick={() => aiAssistantStore.open({
                  page: 'intraday',
                  phase: 'intraday',
                  target: { type: 'stock', name: row.name, data: { ...row, capital_direction: direction } },
                }, `${row.name}为什么出现${money(row.net_amount_yi)}的资金净额？结合涨跌、成交、所属行业和近期走势，判断这笔资金是否有效。`)}
                className="ml-1 flex h-8 w-8 shrink-0 items-center justify-center rounded text-gray-600 hover:bg-blue-950/60 hover:text-blue-300"
              >
                <MessageCircleQuestion className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="px-4 py-6 text-sm text-gray-500">正在读取盘中个股资金排名...</div>
      )}
    </div>
  )
}

export default function StockCapitalRanking({ onSelectStock }: Props) {
  const [data, setData] = useState<StockCapitalData | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (force = false) => {
    setLoading(true)
    try {
      const response = await fetch(`/api/market-radar/stock-capital${force ? '?refresh=true' : ''}`)
      const payload = await response.json() as StockCapitalData
      setData(payload)
    } catch (cause) {
      setData(previous => ({
        ...(previous || {}),
        error: cause instanceof Error ? cause.message : '实时个股资金榜读取失败',
      }))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 60_000)
    return () => window.clearInterval(timer)
  }, [load])

  return (
    <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
      <div className="flex items-center justify-between gap-4 border-b border-gray-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <Landmark className="h-4 w-4 text-blue-400" />
          <div>
            <h2 className="text-sm font-semibold text-white">实时个股资金榜</h2>
            <p className="mt-0.5 text-xs text-gray-600">全市场股票按盘中资金净额排序，点击股票查看详情</p>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className={data?.stale ? 'text-amber-300' : 'text-gray-500'}>
            {data?.stale ? '最近成功数据' : '每60秒更新'} · {data?.updated_at || '--'}
          </span>
          <button
            type="button"
            onClick={() => void load(true)}
            disabled={loading}
            title="立即刷新个股资金榜"
            className="flex h-8 w-8 items-center justify-center rounded border border-gray-700 text-gray-500 hover:bg-gray-800 hover:text-gray-200 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>
      {data?.error && !(data.inflow?.length || data.outflow?.length) ? (
        <div className="border-b border-red-900/50 bg-red-950/20 px-4 py-3 text-sm text-red-300">{data.error}</div>
      ) : null}
      <div className="grid gap-px bg-gray-800 lg:grid-cols-2">
        <RankingColumn title="资金净流入前十" rows={data?.inflow || []} direction="inflow" onSelectStock={onSelectStock} />
        <RankingColumn title="资金净流出前十" rows={data?.outflow || []} direction="outflow" onSelectStock={onSelectStock} />
      </div>
      <div className="border-t border-gray-800 px-4 py-2 text-xs leading-5 text-gray-600">
        {data?.source ? `${data.source} · ` : ''}{data?.note || '净额按数据商成交分类推算，不代表交易所披露的真实账户资金流向。'}
      </div>
    </section>
  )
}
