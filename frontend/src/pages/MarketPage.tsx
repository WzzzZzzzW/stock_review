/**
 * 行情页 — 行业/概念板块导航模式
 * 所有板块以色块展示，点开显示详情
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

// ── 类型 ──────────────────────────────────────────────────────────────
interface IndustryItem {
  name: string
  pct: string
  pct_num: number
  up_count: string
  down_count: string
  net_in: string
  leader: string
}

interface SummaryResponse {
  industries: IndustryItem[]
  updated_at: string
}

interface ConceptItem {
  name: string
  code: string
  pct: string
  pct_num: number
  leader: string
  leader_pct: number
  company_count: number
}

interface ConceptsResponse {
  concepts: ConceptItem[]
  updated_at: string
}

interface StockItem {
  symbol: string
  name: string
  price: number
  pct: number
  mktcap: number
  volume: string
  turnover: string
}

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
}

// ── 颜色工具 ──────────────────────────────────────────────────────────
function pctBg(v: number): string {
  if (v >= 5)   return 'bg-red-700/90 border-red-600'
  if (v >= 3)   return 'bg-red-600/80 border-red-500'
  if (v >= 1)   return 'bg-red-500/60 border-red-400'
  if (v >= 0)   return 'bg-red-900/40 border-red-800'
  if (v >= -1)  return 'bg-emerald-900/40 border-emerald-800'
  if (v >= -3)  return 'bg-emerald-600/60 border-emerald-500'
  if (v >= -5)  return 'bg-emerald-700/80 border-emerald-600'
  return 'bg-emerald-800/90 border-emerald-700'
}

function pctText(v: number): string {
  if (Math.abs(v) >= 3) return 'text-white font-bold'
  if (v >= 0) return 'text-red-300'
  return 'text-emerald-300'
}

function pctStr(v: number): string {
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
}

function stockPctColor(v: number): string {
  if (v > 0) return 'text-red-400'
  if (v < 0) return 'text-emerald-400'
  return 'text-gray-400'
}

// ── 行业成分股弹窗 ────────────────────────────────────────────────────
function IndustryPanel({
  industry,
  onClose,
  onSelectStock,
}: {
  industry: IndustryItem
  onClose: () => void
  onSelectStock?: (symbol: string, name: string) => void
}) {
  const { data: stocks = [], isLoading } = useQuery<StockItem[]>({
    queryKey: ['industry-stocks', industry.name],
    queryFn: async () => {
      const res = await fetch(`/api/industry/stocks/${encodeURIComponent(industry.name)}`)
      if (!res.ok) throw new Error('获取成分股失败')
      return res.json()
    },
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl">
        {/* 头部 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 shrink-0">
          <div>
            <h2 className="text-white font-bold text-lg">{industry.name}</h2>
            <div className="flex gap-3 mt-1 text-xs text-gray-500">
              <span>今日 <b className={industry.pct_num >= 0 ? 'text-red-400' : 'text-emerald-400'}>{industry.pct}</b></span>
              <span>↑ <b className="text-red-400">{industry.up_count}</b> 家</span>
              <span>↓ <b className="text-emerald-400">{industry.down_count}</b> 家</span>
              {industry.leader && industry.leader !== '--' && (
                <span>领涨：<b className="text-yellow-400">{industry.leader}</b></span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white text-2xl leading-none w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-800 transition-colors"
          >×</button>
        </div>

        {/* 成分股列表 */}
        <div className="overflow-y-auto flex-1">
          {isLoading ? (
            <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
              <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mr-2" />
              加载成分股...
            </div>
          ) : stocks.length === 0 ? (
            <div className="text-center py-12 text-gray-600 text-sm">暂无成分股数据</div>
          ) : (
            <>
              <div className="px-5 py-2 text-xs text-gray-600">{stocks.length} 只成分股，按今日涨幅排序</div>
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-gray-900/95">
                  <tr className="text-xs text-gray-500 border-b border-gray-800">
                    <th className="text-left px-5 py-2">#</th>
                    <th className="text-left px-2 py-2">股票</th>
                    <th className="text-right px-4 py-2">最新价</th>
                    <th className="text-right px-4 py-2">涨跌幅</th>
                    <th className="text-right px-4 py-2 hidden sm:table-cell">市值(亿)</th>
                    <th className="text-right px-5 py-2 hidden sm:table-cell">换手率</th>
                  </tr>
                </thead>
                <tbody>
                  {stocks.map((s, i) => (
                    <tr
                      key={s.symbol}
                      className="border-t border-gray-800/40 hover:bg-gray-800/50 transition-colors cursor-pointer group"
                      onClick={() => { onSelectStock?.(s.symbol, s.name); onClose() }}
                    >
                      <td className="px-5 py-2.5 text-gray-600 text-xs w-8">{i + 1}</td>
                      <td className="px-2 py-2.5">
                        <div className="font-medium text-gray-200 group-hover:text-white transition-colors">{s.name}</div>
                        <div className="text-xs text-gray-600">{s.symbol}</div>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums text-gray-300">
                        {s.price > 0 ? `¥${s.price}` : '--'}
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono tabular-nums font-semibold ${stockPctColor(s.pct)}`}>
                        {pctStr(s.pct)}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-500 text-xs hidden sm:table-cell">
                        {s.mktcap > 0 ? s.mktcap.toFixed(0) : '--'}
                      </td>
                      <td className="px-5 py-2.5 text-right text-gray-500 text-xs hidden sm:table-cell">
                        {s.turnover !== '--' ? s.turnover + '%' : '--'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>

        {/* 底部操作 */}
        <div className="px-5 py-3 border-t border-gray-800 text-xs text-gray-600 shrink-0">
          点击股票 → 跳转复盘页
        </div>
      </div>
    </div>
  )
}

// ── 概念板块详情弹窗 ──────────────────────────────────────────────────
function ConceptPanel({
  concept,
  onClose,
}: {
  concept: ConceptItem
  onClose: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-md flex flex-col shadow-2xl">
        {/* 头部 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 shrink-0">
          <div>
            <h2 className="text-white font-bold text-lg">{concept.name}</h2>
            <div className="flex flex-wrap gap-3 mt-1 text-xs text-gray-500">
              <span>板块代码 <b className="text-gray-400">{concept.code || '--'}</b></span>
              <span>成员 <b className="text-blue-400">{concept.company_count}</b> 家</span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white text-2xl leading-none w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-800 transition-colors"
          >×</button>
        </div>

        {/* 概念详情 */}
        <div className="px-5 py-5 flex flex-col gap-4">
          {/* 今日表现 */}
          <div className="bg-gray-800/60 rounded-xl p-4 flex items-center justify-between">
            <span className="text-gray-400 text-sm">今日涨跌幅</span>
            <span className={`text-2xl font-bold tabular-nums ${concept.pct_num >= 0 ? 'text-red-400' : 'text-emerald-400'}`}>
              {concept.pct}
            </span>
          </div>

          {/* 领涨股 */}
          {concept.leader && concept.leader.trim() !== '' && (
            <div className="bg-gray-800/60 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-gray-500 text-xs mb-1">领涨股</div>
                <div className="text-white font-semibold">{concept.leader}</div>
              </div>
              <span className={`text-lg font-bold tabular-nums ${concept.leader_pct >= 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                {concept.leader_pct > 0 ? '+' : ''}{concept.leader_pct.toFixed(2)}%
              </span>
            </div>
          )}

          {/* 成员数量 */}
          <div className="bg-gray-800/60 rounded-xl p-4 flex items-center justify-between">
            <span className="text-gray-400 text-sm">成员公司数</span>
            <span className="text-white font-semibold">{concept.company_count} 家</span>
          </div>
        </div>

        <div className="px-5 py-3 border-t border-gray-800 text-xs text-gray-600 shrink-0">
          数据来源：新浪财经概念板块
        </div>
      </div>
    </div>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────
export default function MarketPage({ onSelectStock }: Props) {
  const [activeTab, setActiveTab] = useState<'industry' | 'concept'>('industry')
  const [selectedIndustry, setSelectedIndustry] = useState<IndustryItem | null>(null)
  const [selectedConcept, setSelectedConcept] = useState<ConceptItem | null>(null)
  const [filter, setFilter] = useState('')
  const [sortBy, setSortBy] = useState<'pct' | 'name'>('pct')

  // ── 行业数据 ────────────────────────────────────────────────────────
  const { data: summaryData, isLoading: industryLoading, refetch: refetchIndustry } = useQuery<SummaryResponse>({
    queryKey: ['industry-summary'],
    queryFn: async () => {
      const res = await fetch('/api/industry/summary')
      if (!res.ok) throw new Error('行业数据获取失败')
      return res.json()
    },
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  })
  const industries: IndustryItem[] = summaryData?.industries ?? []
  const industryUpdatedAt: string = summaryData?.updated_at ?? ''

  // ── 概念数据 ────────────────────────────────────────────────────────
  const { data: conceptsData, isLoading: conceptLoading, refetch: refetchConcepts } = useQuery<ConceptsResponse>({
    queryKey: ['sector-concepts'],
    queryFn: async () => {
      const res = await fetch('/api/sector/concepts')
      if (!res.ok) throw new Error('概念板块数据获取失败')
      return res.json()
    },
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
    enabled: activeTab === 'concept',
  })
  const concepts: ConceptItem[] = conceptsData?.concepts ?? []
  const conceptUpdatedAt: string = conceptsData?.updated_at ?? ''

  // ── 当前 tab 的数据 ─────────────────────────────────────────────────
  const isLoading = activeTab === 'industry' ? industryLoading : conceptLoading
  const updatedAt  = activeTab === 'industry' ? industryUpdatedAt : conceptUpdatedAt

  const sortedIndustries = useMemo(() => {
    const filtered = filter
      ? industries.filter(i => i.name.includes(filter))
      : industries
    return [...filtered].sort((a, b) =>
      sortBy === 'pct'
        ? (b.pct_num ?? 0) - (a.pct_num ?? 0)
        : a.name.localeCompare(b.name)
    )
  }, [industries, filter, sortBy])

  const sortedConcepts = useMemo(() => {
    const filtered = filter
      ? concepts.filter(c => c.name.includes(filter))
      : concepts
    return [...filtered].sort((a, b) =>
      sortBy === 'pct'
        ? (b.pct_num ?? 0) - (a.pct_num ?? 0)
        : a.name.localeCompare(b.name)
    )
  }, [concepts, filter, sortBy])

  // ── 概况统计 ────────────────────────────────────────────────────────
  const risingCount  = activeTab === 'industry'
    ? industries.filter(i => (i.pct_num ?? 0) > 0).length
    : concepts.filter(c => (c.pct_num ?? 0) > 0).length
  const fallingCount = activeTab === 'industry'
    ? industries.filter(i => (i.pct_num ?? 0) < 0).length
    : concepts.filter(c => (c.pct_num ?? 0) < 0).length

  const topIndustry = industries.length > 0
    ? industries.reduce((a, b) => ((a.pct_num ?? 0) > (b.pct_num ?? 0) ? a : b), industries[0])
    : null
  const topConcept = concepts.length > 0
    ? concepts.reduce((a, b) => ((a.pct_num ?? 0) > (b.pct_num ?? 0) ? a : b), concepts[0])
    : null

  const handleRefetch = () => {
    if (activeTab === 'industry') refetchIndustry()
    else refetchConcepts()
  }

  const searchPlaceholder = activeTab === 'industry' ? '搜索行业名称...' : '搜索概念名称...'

  return (
    <div className="min-h-screen bg-gray-950">

      {/* 顶部控制栏 */}
      <div className="sticky top-12 z-30 bg-gray-950/95 backdrop-blur border-b border-gray-800 px-4 py-2.5">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center gap-3">

          {/* Tab 切换 */}
          <div className="flex gap-1">
            {([['industry', '行业板块'], ['concept', '概念板块']] as const).map(([k, label]) => (
              <button key={k} onClick={() => { setActiveTab(k); setFilter('') }}
                className={`text-xs px-3 py-1.5 rounded-lg transition-colors font-medium ${
                  activeTab === k
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:text-white'
                }`}>{label}</button>
            ))}
          </div>

          {/* 分隔 */}
          <div className="w-px h-4 bg-gray-700 hidden sm:block" />

          {/* 市场概况 */}
          <div className="flex gap-4 text-xs">
            <span className="text-gray-500">
              上涨 <b className="text-red-400">{risingCount}</b>
            </span>
            <span className="text-gray-500">
              下跌 <b className="text-emerald-400">{fallingCount}</b>
            </span>
            {activeTab === 'industry' && topIndustry && (
              <span className="text-gray-500 hidden sm:block">
                今日最强 <b className="text-yellow-400">{topIndustry.name}</b> {topIndustry.pct}
              </span>
            )}
            {activeTab === 'concept' && topConcept && (
              <span className="text-gray-500 hidden sm:block">
                今日最强 <b className="text-yellow-400">{topConcept.name}</b> {topConcept.pct}
              </span>
            )}
          </div>

          <input
            type="text"
            placeholder={searchPlaceholder}
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="flex-1 min-w-28 max-w-48 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-300 placeholder-gray-600 outline-none focus:border-blue-500"
          />

          <div className="flex gap-1.5">
            {([['pct', '涨幅排序'], ['name', '名称排序']] as const).map(([k, label]) => (
              <button key={k} onClick={() => setSortBy(k)}
                className={`text-xs px-2.5 py-1.5 rounded-lg transition-colors ${
                  sortBy === k ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
                }`}>{label}</button>
            ))}
          </div>

          {updatedAt && (
            <span className="text-xs text-gray-600 hidden sm:block">
              数据更新 <b className="text-gray-500">{updatedAt}</b>
            </span>
          )}

          <button onClick={handleRefetch}
            className="text-xs text-gray-500 hover:text-white border border-gray-800 rounded-lg px-2.5 py-1.5 transition-colors">
            🔄 刷新
          </button>
        </div>
      </div>

      {/* 板块色块 */}
      <div className="max-w-7xl mx-auto px-4 py-5">
        {isLoading ? (
          <div className="flex items-center justify-center h-72 text-gray-500">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mr-3" />
            <span className="text-sm">
              {activeTab === 'industry' ? '加载行业数据...' : '加载概念数据...'}
            </span>
          </div>
        ) : activeTab === 'industry' ? (
          <>
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-2">
              {sortedIndustries.map(industry => {
                const v = industry.pct_num ?? 0
                return (
                  <button
                    key={industry.name}
                    onClick={() => setSelectedIndustry(industry)}
                    className={`
                      flex flex-col items-center justify-center
                      rounded-xl border px-2 py-3.5 gap-1
                      transition-all duration-150 hover:scale-[1.06] hover:shadow-xl hover:z-10
                      cursor-pointer text-center select-none
                      ${pctBg(v)}
                    `}
                  >
                    <span className={`text-xs leading-tight ${pctText(v)}`}>
                      {industry.name}
                    </span>
                    <span className={`text-[15px] leading-none tabular-nums mt-0.5 ${pctText(v)}`}>
                      {pctStr(v)}
                    </span>
                    {industry.leader && industry.leader !== '--' && (
                      <span className="text-[9px] text-white/50 truncate w-full px-1">
                        {industry.leader}
                      </span>
                    )}
                    <div className="flex gap-1.5 text-[9px] mt-0.5">
                      <span className="text-red-300/60">↑{industry.up_count}</span>
                      <span className="text-emerald-300/60">↓{industry.down_count}</span>
                    </div>
                  </button>
                )
              })}
            </div>
            {sortedIndustries.length === 0 && filter && (
              <p className="text-center text-gray-600 py-16">
                未找到「{filter}」相关行业
              </p>
            )}
          </>
        ) : (
          <>
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-2">
              {sortedConcepts.map(concept => {
                const v = concept.pct_num ?? 0
                return (
                  <button
                    key={concept.code || concept.name}
                    onClick={() => setSelectedConcept(concept)}
                    className={`
                      flex flex-col items-center justify-center
                      rounded-xl border px-2 py-3.5 gap-1
                      transition-all duration-150 hover:scale-[1.06] hover:shadow-xl hover:z-10
                      cursor-pointer text-center select-none
                      ${pctBg(v)}
                    `}
                  >
                    <span className={`text-xs leading-tight ${pctText(v)}`}>
                      {concept.name}
                    </span>
                    <span className={`text-[15px] leading-none tabular-nums mt-0.5 ${pctText(v)}`}>
                      {pctStr(v)}
                    </span>
                    {concept.leader && concept.leader.trim() !== '' && (
                      <span className="text-[9px] text-white/50 truncate w-full px-1">
                        {concept.leader}
                      </span>
                    )}
                    <div className="text-[9px] mt-0.5 text-white/30">
                      {concept.company_count}家
                    </div>
                  </button>
                )
              })}
            </div>
            {sortedConcepts.length === 0 && filter && (
              <p className="text-center text-gray-600 py-16">
                未找到「{filter}」相关概念
              </p>
            )}
            {sortedConcepts.length === 0 && !filter && !conceptLoading && (
              <p className="text-center text-gray-600 py-16">
                暂无概念板块数据
              </p>
            )}
          </>
        )}
      </div>

      {/* 行业成分股弹窗 */}
      {selectedIndustry && (
        <IndustryPanel
          industry={selectedIndustry}
          onClose={() => setSelectedIndustry(null)}
          onSelectStock={onSelectStock}
        />
      )}

      {/* 概念板块详情弹窗 */}
      {selectedConcept && (
        <ConceptPanel
          concept={selectedConcept}
          onClose={() => setSelectedConcept(null)}
        />
      )}
    </div>
  )
}
