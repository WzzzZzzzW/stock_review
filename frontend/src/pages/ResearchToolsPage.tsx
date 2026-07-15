import { useEffect, useState } from 'react'
import { Activity, BarChart3, Building2, CandlestickChart, Newspaper, Search, Swords } from 'lucide-react'
import ErrorBoundary from '../components/ErrorBoundary'
import LhbPage from './LhbPage'
import LimitUpReviewPage from './LimitUpReviewPage'
import MarketPage from './MarketPage'
import NewsImpactPage from './NewsImpactPage'
import ReviewPage from './ReviewPage'
import ScreenerPage from './ScreenerPage'

export type ResearchSection = 'market' | 'limitup' | 'lhb' | 'industry' | 'news' | 'review' | 'screener'

interface Props {
  section: ResearchSection
  onSectionChange: (section: ResearchSection) => void
  reviewSymbol?: string
  reviewName?: string
  onSelectStock?: (symbol: string, name: string) => void
}

const tabs: { key: ResearchSection; label: string; icon: typeof Activity }[] = [
  { key: 'market', label: '大盘证据', icon: Activity },
  { key: 'limitup', label: '涨停证据', icon: CandlestickChart },
  { key: 'lhb', label: '龙虎榜', icon: Swords },
  { key: 'industry', label: '行业板块', icon: Building2 },
  { key: 'news', label: '新闻', icon: Newspaper },
  { key: 'review', label: '个股复盘', icon: BarChart3 },
  { key: 'screener', label: '行业选股', icon: Search },
]

interface DailyReport {
  updated_at?: string
  indices?: { key: string; name: string; price: number; pct: number; high?: number; low?: number }[]
  sentiment?: { label?: string; level?: string }
  sectors?: {
    top_up?: { name: string; pct: number; leader?: string }[]
    top_down?: { name: string; pct: number; leader?: string }[]
    up_count?: number
    down_count?: number
    total?: number
  }
}

function pctClass(value: number) {
  return value > 0 ? 'text-red-400' : value < 0 ? 'text-emerald-400' : 'text-gray-400'
}

function MarketEvidence() {
  const [data, setData] = useState<DailyReport | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/daily-report')
      .then(async response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then(setData)
      .catch(cause => setError(cause instanceof Error ? cause.message : '读取失败'))
  }, [])

  return (
    <main className="mx-auto max-w-7xl px-4 py-5">
      {error ? <div className="border-l-2 border-red-500 px-3 py-2 text-sm text-red-300">{error}</div> : !data ? (
        <div className="py-12 text-center text-sm text-gray-500">正在读取大盘证据...</div>
      ) : (
        <div className="space-y-4">
          <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
            <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
              <h2 className="text-sm font-semibold text-white">核心指数</h2>
              <span className="text-xs text-gray-600">{data.updated_at || '--'} 更新</span>
            </div>
            <div className="grid gap-px bg-gray-800 sm:grid-cols-2 lg:grid-cols-4">
              {(data.indices ?? []).map(index => (
                <div key={index.key} className="bg-gray-900 px-4 py-4">
                  <div className="text-xs text-gray-500">{index.name}</div>
                  <div className="mt-1 flex items-baseline justify-between">
                    <span className="text-lg font-semibold text-white">{index.price}</span>
                    <span className={`font-medium ${pctClass(index.pct)}`}>{index.pct > 0 ? '+' : ''}{index.pct.toFixed(2)}%</span>
                  </div>
                  <div className="mt-2 text-xs text-gray-600">高 {index.high || '--'} · 低 {index.low || '--'}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
            <div className="grid gap-px bg-gray-800 lg:grid-cols-3">
              <div className="bg-gray-900 px-4 py-4">
                <div className="text-xs text-gray-500">市场结论</div>
                <div className="mt-1 text-lg font-semibold text-blue-300">{data.sentiment?.label || '数据不足'}</div>
              </div>
              <div className="bg-gray-900 px-4 py-4">
                <div className="text-xs text-gray-500">板块广度</div>
                <div className="mt-1 text-sm text-gray-200">上涨 {data.sectors?.up_count ?? 0} · 下跌 {data.sectors?.down_count ?? 0} · 共 {data.sectors?.total ?? 0}</div>
              </div>
              <div className="bg-gray-900 px-4 py-4">
                <div className="text-xs text-gray-500">执行判断</div>
                <div className="mt-1 text-sm leading-5 text-gray-200">
                  {(data.sectors?.up_count ?? 0) > (data.sectors?.down_count ?? 0) ? '资金扩散占优，优先做强板块前排。' : '弱势板块占优，缩仓并只保留逆势强股。'}
                </div>
              </div>
            </div>
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
              <h2 className="border-b border-gray-800 px-4 py-3 text-sm font-semibold text-red-300">领涨证据</h2>
              <div className="divide-y divide-gray-800">
                {(data.sectors?.top_up ?? []).map(item => (
                  <div key={item.name} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                    <div><span className="text-white">{item.name}</span><span className="ml-2 text-xs text-gray-600">{item.leader || '--'}</span></div>
                    <span className={pctClass(item.pct)}>+{item.pct.toFixed(2)}%</span>
                  </div>
                ))}
              </div>
            </section>
            <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
              <h2 className="border-b border-gray-800 px-4 py-3 text-sm font-semibold text-emerald-300">领跌证据</h2>
              <div className="divide-y divide-gray-800">
                {(data.sectors?.top_down ?? []).map(item => (
                  <div key={item.name} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                    <div><span className="text-white">{item.name}</span><span className="ml-2 text-xs text-gray-600">{item.leader || '--'}</span></div>
                    <span className={pctClass(item.pct)}>{item.pct.toFixed(2)}%</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}
    </main>
  )
}

export default function ResearchToolsPage({ section, onSectionChange, reviewSymbol = '', reviewName = '', onSelectStock }: Props) {
  return (
    <div>
      <div className="border-b border-gray-800 bg-gray-950/95">
        <div className="mx-auto flex max-w-7xl items-center gap-1 overflow-x-auto px-4 py-2">
          {tabs.map(tab => {
            const Icon = tab.icon
            return (
              <button
                key={tab.key}
                onClick={() => onSectionChange(tab.key)}
                className={`inline-flex h-8 shrink-0 items-center gap-2 rounded px-3 text-xs font-medium transition-colors ${section === tab.key ? 'bg-gray-700 text-white' : 'text-gray-500 hover:bg-gray-900 hover:text-gray-300'}`}
              >
                <Icon className="h-3.5 w-3.5" />{tab.label}
              </button>
            )
          })}
        </div>
      </div>
      {section === 'market' && <ErrorBoundary name="research-market"><MarketEvidence /></ErrorBoundary>}
      {section === 'limitup' && <ErrorBoundary name="research-limitup"><LimitUpReviewPage /></ErrorBoundary>}
      {section === 'lhb' && <ErrorBoundary name="research-lhb"><LhbPage onSelectStock={onSelectStock} /></ErrorBoundary>}
      {section === 'industry' && <ErrorBoundary name="research-industry"><MarketPage onSelectStock={onSelectStock} /></ErrorBoundary>}
      {section === 'news' && <ErrorBoundary name="research-news"><NewsImpactPage /></ErrorBoundary>}
      {section === 'review' && <ErrorBoundary name="research-review"><ReviewPage defaultSymbol={reviewSymbol} defaultName={reviewName} /></ErrorBoundary>}
      {section === 'screener' && <ErrorBoundary name="research-screener"><ScreenerPage /></ErrorBoundary>}
    </div>
  )
}
