import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { RefreshCw } from 'lucide-react'
import MarketRadarEvaluation from '../components/MarketRadarEvaluation'
import { useWatchlist } from '../stores/watchlistStore'

type DateRow = {
  date: string
  sentiment_score: number
  position_count: number
  watch_count: number
  generated_at: string
}

type MarketStatus = {
  phase: 'premarket' | 'intraday' | 'postmarket'
  label: string
  today: string
  completed_trade_date: string
  can_generate_postmarket: boolean
}

type MultiDecision = {
  score: number
  action: string
  rank?: number
  summary: string
  trigger?: string
  confidence?: string
  coverage?: number
  dimensions?: { key: string; label: string; score: number; evidence: string }[]
}

type Stock = {
  symbol: string
  name: string
  price?: number
  pct_change?: number
  today_pnl?: number
  pnl_pct?: number
  current_value?: number
  turnover?: number
  amount_yi?: number
  change_pct?: number
  logic?: string
  tech?: {
    vol_ratio?: number
    ma20_gap_pct?: number
    macd_state?: string
    turnover?: number
    close?: number
  }
  decision?: MultiDecision
}

type DistBin = { label: string; count: number; side: 'up' | 'down' }
type LadderRow = { height: number; count: number; names: string[] }
type CapTier = { tier: string; count: number; avg_pct: number; up: number; down: number }
type SectorItem = { name: string; pct: number; leader: string; type: string }
type NewsItem = { title: string; summary?: string; source?: string; published?: string; url?: string }
type IndexItem = { key?: string; name?: string; price?: number; pct?: number }
type DataInsight = { title: string; evidence: string; meaning: string; tone?: 'red' | 'green' | 'blue' | 'amber' }

type MarketData = {
  summary?: string
  sentiment?: { score?: number; label?: string; emoji?: string; color?: string; desc?: string; index_avg?: number }
  breadth?: { up?: number; down?: number; flat?: number; total?: number; up_ratio?: number; up_over5?: number; down_over5?: number }
  distribution?: DistBin[]
  limit_stats?: {
    zt_count?: number
    dt_count?: number
    broken_count?: number
    broken_ratio?: number
    max_continuity?: number
    ladder?: LadderRow[]
    zt_by_industry?: { industry: string; count: number }[]
    dt_stocks?: { symbol: string; name: string; pct: number; dt_days?: number }[]
  }
  indices?: IndexItem[]
  amount?: { total_yi?: number }
  rankings?: { gainers?: Stock[]; losers?: Stock[]; amount?: Stock[]; turnover?: Stock[] }
  cap_perf?: CapTier[]
  sectors?: { top_up?: SectorItem[]; top_down?: SectorItem[] }
  news?: NewsItem[]
  leaders?: Stock[]
  laggards?: Stock[]
  ai_review?: string
}

type Industry = {
  name: string
  pct?: string
  pct_num?: number
  up_count?: string
  down_count?: string
  leader?: string
  net_in?: string
  decision?: MultiDecision
}

type Trend = {
  title?: string
  summary?: string
  impact_score?: number
  direction?: string
  stocks?: { symbol?: string; name?: string }[]
}

type TodayReview = {
  trade_date: string
  generated_at: string
  market: MarketData
  analysis?: {
    market_review?: string
    portfolio_review?: string
    watchlist_review?: string
    industry_review?: string
    international_review?: string
    error?: string
  }
  portfolio: {
    conclusion?: string
    summary?: { total_value?: number; total_pnl_amount?: number; total_pnl_pct?: number; today_pnl?: number; position_count?: number }
    positions?: Stock[]
    top_winners?: Stock[]
    top_losers?: Stock[]
    alerts?: { level?: string; text?: string }[]
  }
  watchlist: {
    conclusion?: string
    summary?: { count?: number; up?: number; down?: number; avg_pct?: number }
    stocks?: Stock[]
    top_winners?: Stock[]
    top_losers?: Stock[]
  }
  industry: {
    conclusion?: string
    top_up?: Industry[]
    top_down?: Industry[]
  }
  international: {
    conclusion?: string
    items?: Trend[]
  }
  risk_opportunity?: {
    risks?: string[]
    opportunities?: string[]
  }
  tomorrow_watch?: string[]
}

function todayStr() {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function ymd(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function dateFromYmd(s: string) {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, (m || 1) - 1, d || 1)
}

function fmtTime(v?: string) {
  if (!v) return ''
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function pctClass(v?: number) {
  const n = Number(v || 0)
  if (n > 0) return 'text-red-300'
  if (n < 0) return 'text-emerald-300'
  return 'text-gray-300'
}

function fmtPct(v?: number) {
  const n = Number(v || 0)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

function stockPct(s?: Stock) {
  return Number(s?.pct_change ?? s?.change_pct ?? 0)
}

const marketPctColor = (v: number | null | undefined) =>
  v == null ? 'text-gray-400' : v > 0 ? 'text-red-400' : v < 0 ? 'text-green-400' : 'text-gray-300'

function fmtMoney(v?: number) {
  const n = Number(v || 0)
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(2)}万`
  return n.toFixed(2)
}

function safeNum(v: unknown) {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function buildMarketInsights(market?: MarketData): DataInsight[] {
  if (!market) return []
  const b = market.breadth || {}
  const ls = market.limit_stats || {}
  const amount = safeNum(market.amount?.total_yi)
  const up = safeNum(b.up)
  const down = safeNum(b.down)
  const upRatio = safeNum(b.up_ratio) || (up + down ? up / (up + down) * 100 : 0)
  const upOver5 = safeNum(b.up_over5)
  const downOver5 = safeNum(b.down_over5)
  const zt = safeNum(ls.zt_count)
  const dt = safeNum(ls.dt_count)
  const broken = safeNum(ls.broken_count)
  const brokenRatio = safeNum(ls.broken_ratio)
  const indices = market.indices || []
  const sh = indices.find(x => x.key === 'sh' || x.name?.includes('上证'))
  const cyb = indices.find(x => x.key === 'cyb' || x.name?.includes('创业'))
  const sz = indices.find(x => x.key === 'sz' || x.name?.includes('深证'))
  const indexPcts = indices.map(x => safeNum(x.pct))
  const divergence = indexPcts.length ? Math.max(...indexPcts) - Math.min(...indexPcts) : 0
  const cap = market.cap_perf || []
  const small = cap.find(x => x.tier.includes('小盘 <50亿'))
  const mega = cap.find(x => x.tier.includes('超大盘'))
  const midSmall = cap.find(x => x.tier.includes('中小盘'))
  const topUp = market.sectors?.top_up || []
  const topDown = market.sectors?.top_down || []
  const ztIndustry = ls.zt_by_industry || []
  const dist = market.distribution || []
  const up7 = safeNum(dist.find(x => x.label.includes('涨幅>7'))?.count)
  const down7 = safeNum(dist.find(x => x.label.includes('跌幅>7'))?.count)
  const amountTop = (market.rankings?.amount || []).slice(0, 5).map(x => x.name).filter(Boolean).join('、')
  const gainers = (market.rankings?.gainers || []).slice(0, 5).map(x => `${x.name}${fmtPct(stockPct(x))}`).join('、')
  const topSectorNames = topUp.slice(0, 5).map(x => `${x.name}${fmtPct(x.pct)}`).join('、')
  const weakSectorNames = topDown.slice(0, 4).map(x => `${x.name}${fmtPct(x.pct)}`).join('、')
  const ztIndustryNames = ztIndustry.slice(0, 4).map(x => `${x.industry}${x.count}只`).join('、')

  const insights: DataInsight[] = []
  if (up && down) {
    insights.push({
      title: upRatio >= 70 ? '不是指数硬拉，是多数股票一起修复' : '市场参与度一般，指数参考价值更高',
      evidence: `${Math.round(up)}涨 / ${Math.round(down)}跌，上涨占比 ${upRatio.toFixed(1)}%；涨超5% ${Math.round(upOver5)} 只，跌超5% ${Math.round(downOver5)} 只。`,
      meaning: upRatio >= 70
        ? '当天赚钱效应来自广度扩散，短线选股比单看指数更重要；明天重点看这个广度能否维持在 60% 以上。'
        : '上涨没有充分扩散，行情更依赖少数权重或主题，追高要更看个股位置。',
      tone: upRatio >= 70 ? 'red' : 'amber',
    })
  }
  if (indices.length >= 2) {
    insights.push({
      title: divergence >= 1.5 ? '指数分化很大，风格切换比指数涨跌更重要' : '指数同步性较好，方向判断更简单',
      evidence: `上证 ${fmtPct(sh?.pct)}，深成指 ${fmtPct(sz?.pct)}，创业板 ${fmtPct(cyb?.pct)}，主要指数最大分化约 ${divergence.toFixed(2)} 个百分点。`,
      meaning: divergence >= 1.5
        ? '资金并不是无脑做多，而是在金融/防御/低位和成长高位之间切换；成长持仓降一级处理，只保留承接最强的票。'
        : '指数方向相对一致，板块主线和指数节奏更容易共振。',
      tone: divergence >= 1.5 ? 'amber' : 'blue',
    })
  }
  if (small && mega) {
    const gap = safeNum(small.avg_pct) - safeNum(mega.avg_pct)
    const smallWin = safeNum(small.avg_pct) > safeNum(mega.avg_pct)
    insights.push({
      title: smallWin ? '小盘明显强于权重，弹性在小市值' : '权重强于小盘，指数权重更关键',
      evidence: `小盘<50亿平均 ${fmtPct(small.avg_pct)}，中小盘50-100亿平均 ${fmtPct(midSmall?.avg_pct)}，超大盘平均 ${fmtPct(mega.avg_pct)}，小盘领先超大盘 ${gap.toFixed(2)} 个百分点。`,
      meaning: smallWin
        ? '当天主战场在弹性票和题材票，明天优先做小盘弹性；小盘掉队时立刻切回防守，不做弱反弹。'
        : '行情更偏权重驱动，小票不进主计划，只保留已经走出强度的个股。',
      tone: smallWin ? 'red' : 'blue',
    })
  }
  if (zt || broken) {
    const brokenToZt = zt ? broken / zt * 100 : 0
    insights.push({
      title: brokenRatio >= 30 ? '涨停很多，但高位承接并不稳' : '涨停承接较稳，短线接力环境较好',
      evidence: `涨停 ${Math.round(zt)} 只、跌停 ${Math.round(dt)} 只、炸板 ${Math.round(broken)} 只；炸板率 ${brokenRatio.toFixed(1)}%，炸板/涨停约 ${brokenToZt.toFixed(1)}%。`,
      meaning: brokenRatio >= 30
        ? '资金敢进攻，但封板质量一般，明天要看炸板率是否降到 25% 以下；否则强势股容易冲高分歧。'
        : '封板成功率较好，接力资金愿意承接，强势主线更容易延续。',
      tone: brokenRatio >= 30 ? 'amber' : 'red',
    })
  }
  if (topSectorNames || ztIndustryNames) {
    insights.push({
      title: '主线不是单一方向，金融防守与题材进攻并存',
      evidence: `涨幅靠前：${topSectorNames || '暂无'}；涨停行业集中：${ztIndustryNames || '暂无'}；弱势方向：${weakSectorNames || '暂无'}。`,
      meaning: '保险等权重负责稳指数，化学制品/制药/养殖等方向负责短线弹性。明天只做权重和题材共振的方向，单独护盘的权重不追，断掉的题材直接剔除。',
      tone: 'blue',
    })
  }
  if (up7 || down7) {
    const tailRatio = down7 ? up7 / down7 : up7
    insights.push({
      title: tailRatio >= 3 ? '强势尾部远多于弱势尾部，情绪仍偏进攻' : '极端涨跌分布不够强，情绪需再确认',
      evidence: `涨幅>7% ${Math.round(up7)} 只，跌幅>7% ${Math.round(down7)} 只，强弱极端比约 ${tailRatio.toFixed(1)} 倍。`,
      meaning: tailRatio >= 3
        ? '强势票数量明显占优，说明资金愿意给高弹性溢价；但要和炸板率一起看，强势多不代表追高安全。'
        : '极端强势股优势不明显，短线不宜过度激进。',
      tone: tailRatio >= 3 ? 'red' : 'amber',
    })
  }
  if (amount || amountTop || gainers) {
    insights.push({
      title: amount >= 25000 ? '成交额足够大，关键看资金流向而不是有没有量' : '成交额不足，主线持续性要打折',
      evidence: `两市成交约 ${Math.round(amount)} 亿；成交额前排：${amountTop || '暂无'}；涨幅前排：${gainers || '暂无'}。`,
      meaning: amount >= 25000
        ? '量能不是问题，问题是增量资金选择哪个方向。成交额前排和涨幅前排重合的主线优先进攻；二者背离时按轮动处理，不追后排。'
        : '量能不足时，板块持续性更依赖消息刺激，追高胜率下降。',
      tone: amount >= 25000 ? 'blue' : 'amber',
    })
  }
  return insights
}

function Section({ title, aside, right, children }: { title: string; aside?: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/70 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          {aside && <span className="truncate text-xs text-gray-500">{aside}</span>}
        </div>
        {right}
      </div>
      {children}
    </section>
  )
}

function ReviewSection({
  index,
  title,
  aside,
  children,
  defaultOpen = false,
}: {
  index: string
  title: string
  aside?: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="overflow-hidden rounded-lg border border-gray-700 bg-gray-900/90 shadow-[0_0_0_1px_rgba(255,255,255,0.03)]">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="flex w-full items-center justify-between gap-4 border-b border-gray-800 bg-gray-900 px-4 py-4 text-left transition-colors hover:bg-gray-800/80"
      >
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-blue-500/60 bg-blue-600/15 font-mono text-sm font-bold text-blue-200">
            {index}
          </span>
          <div className="min-w-0">
            <h2 className="text-xl font-bold leading-tight text-white">{title}</h2>
            {aside && <div className="mt-1 truncate text-xs text-gray-500">{aside}</div>}
          </div>
        </div>
        <span className={`shrink-0 text-sm text-blue-300 transition-transform ${open ? 'rotate-90' : ''}`}>▶</span>
      </button>
      {open && <div className="p-4">{children}</div>}
    </section>
  )
}

function DetailBox({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="overflow-hidden rounded-lg border border-gray-800 bg-gray-950/35">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-gray-900"
      >
        <span className="text-sm font-semibold text-gray-200">{title}</span>
        <span className={`text-xs text-gray-500 transition-transform ${open ? 'rotate-90' : ''}`}>▶</span>
      </button>
      {open && <div className="space-y-3 border-t border-gray-800 p-3">{children}</div>}
    </div>
  )
}

function splitMarkdownSections(text: string) {
  const lines = text.split(/\r?\n/)
  const sections: { title: string; body: string }[] = []
  let intro: string[] = []
  let current: { title: string; body: string[] } | null = null

  for (const line of lines) {
    const match = line.match(/^###\s+(.+?)\s*$/)
    if (match) {
      if (current) sections.push({ title: current.title, body: current.body.join('\n').trim() })
      current = { title: match[1], body: [] }
    } else if (current) {
      current.body.push(line)
    } else {
      intro.push(line)
    }
  }
  if (current) sections.push({ title: current.title, body: current.body.join('\n').trim() })
  const introText = intro.join('\n').trim()
  if (!sections.length) return [{ title: '复盘内容', body: text }]
  return introText ? [{ title: '核心概览', body: introText }, ...sections] : sections
}

function AnalysisMarkdown({ text, title = '复盘分析' }: { text?: string; title?: string }) {
  if (!text) return null
  const sections = splitMarkdownSections(text)
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950/45 px-4 py-3">
      <div className="mb-3 text-xs font-semibold tracking-wide text-blue-300">{title}</div>
      <div className="space-y-4">
        {sections.map((section, index) => (
          <div key={`${section.title}-${index}`} className="border-l-2 border-blue-500/50 pl-3">
            <div className="mb-1.5 text-sm font-bold text-white">{section.title}</div>
            <div className="prose prose-invert prose-sm max-w-none text-gray-300 leading-7 prose-p:my-1.5 prose-li:my-0.5 prose-strong:text-white">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.body}</ReactMarkdown>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: string | number; tone?: 'red' | 'green' | 'blue' }) {
  const color = tone === 'red' ? 'text-red-300' : tone === 'green' ? 'text-emerald-300' : tone === 'blue' ? 'text-blue-300' : 'text-white'
  return (
    <div className="rounded-md border border-gray-800 bg-gray-950/60 px-3 py-2">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className={`mt-1 text-base font-semibold ${color}`}>{value}</div>
    </div>
  )
}

function StockList({ items, empty }: { items?: Stock[]; empty: string }) {
  if (!items?.length) return <div className="text-sm text-gray-500">{empty}</div>
  return (
    <div className="space-y-2">
      {items.slice(0, 5).map(s => (
        <div key={`${s.symbol}-${s.name}`} className="rounded-md bg-gray-950/60 px-3 py-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm text-gray-100">{s.name || s.symbol}</div>
              <div className="text-[11px] text-gray-600">
                {s.symbol}
                {typeof (s.tech as any)?.technical?.vol_ratio === 'number' && <span className="ml-2">量比 {(s.tech as any).technical.vol_ratio.toFixed(2)}</span>}
                {typeof (s.tech as any)?.technical?.ma20_pct === 'number' && <span className="ml-2">距20日线 {fmtPct((s.tech as any).technical.ma20_pct)}</span>}
              </div>
            </div>
            <div className={`shrink-0 text-sm font-semibold ${pctClass(stockPct(s))}`}>{fmtPct(stockPct(s))}</div>
          </div>
          {s.logic && <div className="mt-1.5 text-xs leading-5 text-gray-400">{s.logic}</div>}
        </div>
      ))}
    </div>
  )
}

function stockTech(s: Stock) {
  const tech = (s.tech || {}) as any
  return {
    vol: Number(tech.technical?.vol_ratio ?? tech.vol_ratio ?? 0),
    ma20: Number(tech.technical?.ma20_pct ?? tech.ma20_gap_pct ?? 0),
    macd: String(tech.technical?.macd_status ?? tech.macd_state ?? ''),
    turn: Number(tech.today?.turn ?? s.turnover ?? 0),
    tags: (tech.trend?.tags || []) as string[],
  }
}

function decideStock(s: Stock) {
  const decision = s.decision
  if (!decision || !Number.isFinite(Number(decision.score))) return {
    rank: 50,
    action: '数据待补',
    tone: 'blue' as const,
    reason: '趋势、量价、板块和资金证据尚未覆盖，不依据当日涨跌幅强行裁决。',
    score: 50,
    dimensions: [] as MultiDecision['dimensions'],
  }
  const tone = decision.score >= 68 ? 'red' as const
    : decision.score < 46 ? 'green' as const
      : decision.action.includes('不追') ? 'amber' as const : 'blue' as const
  return {
    ...decision,
    rank: decision.rank ?? 100 - decision.score,
    tone,
    reason: decision.summary,
  }
}

function WatchlistDecisionPanel({ items }: { items?: Stock[] }) {
  if (!items?.length) return <div className="text-sm text-gray-500">暂无自选快照</div>
  const rows = items.map(s => ({ stock: s, decision: decideStock(s) })).sort((a, b) => a.decision.rank - b.decision.rank)
  const keep = rows.filter(x => ['重点进攻', '保留但不追', '保留'].includes(x.decision.action)).length
  const remove = rows.length - keep
  const best = rows[0]
  const toneClass = (tone: 'red' | 'green' | 'blue' | 'amber') => {
    if (tone === 'red') return 'border-red-900/50 bg-red-950/15 text-red-300'
    if (tone === 'green') return 'border-emerald-900/50 bg-emerald-950/15 text-emerald-300'
    if (tone === 'amber') return 'border-amber-900/50 bg-amber-950/15 text-amber-300'
    return 'border-blue-900/50 bg-blue-950/15 text-blue-300'
  }
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-gray-800 bg-gray-950/45 p-3">
        <div className="text-sm font-bold text-white">自选裁决</div>
        <div className="mt-1 text-sm leading-6 text-gray-300">
          结论：{best.decision.action === '剔除'
            ? '这批自选整体不合格，明天先清理弱票。'
            : `只把 ${best.stock.name || best.stock.symbol} 放在第一顺位，其余按裁决降权。`}
          <span className="ml-2 text-xs text-gray-500">保留 {keep} 只 / 剔除或降级 {remove} 只</span>
        </div>
      </div>
      <div className="space-y-2">
        {rows.map(({ stock, decision }) => {
          const t = stockTech(stock)
          return (
            <div key={stock.symbol} className={`rounded-lg border px-3 py-2 ${toneClass(decision.tone)}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-white">{stock.name || stock.symbol}</span>
                    <span className="rounded bg-gray-900 px-2 py-0.5 text-[11px] font-bold">{decision.action}</span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-gray-500">
                    {stock.symbol} · 决策 {decision.score ?? '--'}分 · 覆盖 {stock.decision?.coverage ?? '--'}% · 量比 {t.vol ? t.vol.toFixed(2) : '--'}
                  </div>
                </div>
                <div className={`shrink-0 font-mono text-sm font-bold ${pctClass(stockPct(stock))}`}>{fmtPct(stockPct(stock))}</div>
              </div>
              <div className="mt-1.5 text-xs leading-5 text-gray-300">{decision.reason}</div>
              {!!stock.decision?.dimensions?.length && (
                <div className="mt-1 text-[11px] text-gray-500">
                  {stock.decision.dimensions.slice(0, 5).map(d => `${d.label}${d.score}`).join(' · ')}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function WatchlistExecutionPlan({ items }: { items?: Stock[] }) {
  if (!items?.length) return null
  const rows = items.map(s => ({ stock: s, decision: decideStock(s) })).sort((a, b) => a.decision.rank - b.decision.rank)
  const attack = rows.filter(x => ['重点进攻', '保留但不追'].includes(x.decision.action)).map(x => x.stock.name || x.stock.symbol)
  const backup = rows.filter(x => x.decision.action === '保留').map(x => x.stock.name || x.stock.symbol)
  const cut = rows.filter(x => ['降级', '剔除'].includes(x.decision.action)).map(x => `${x.stock.name || x.stock.symbol}（${x.decision.action}）`)
  const lines = [
    attack.length ? `主攻名单：${attack.join('、')}。只允许这些票进入明日盘中验证。` : '主攻名单：空。自选池没有达到进攻标准的票，明日不从自选里主动开新仓。',
    backup.length ? `备选名单：${backup.join('、')}。只看强承接，不追高，不占主仓位。` : '备选名单：空。没有结构完整但进攻不足的缓冲标的。',
    cut.length ? `清理名单：${cut.join('、')}。这些票不参与明日主计划。` : '清理名单：空。当前自选没有必须剔除或降级的票。',
  ]
  return (
    <div className="rounded-lg border border-blue-900/40 bg-blue-950/10 p-3">
      <div className="mb-2 text-sm font-bold text-blue-200">明日执行</div>
      <ul className="space-y-2 text-xs leading-5 text-gray-300">
        {lines.map((line, i) => <li key={i} className="rounded bg-gray-950/60 px-3 py-2">{line}</li>)}
      </ul>
    </div>
  )
}

function IndustryList({ items, empty }: { items?: Industry[]; empty: string }) {
  if (!items?.length) return <div className="text-sm text-gray-500">{empty}</div>
  return (
    <div className="space-y-2">
      {items.slice(0, 6).map(x => (
        <div key={x.name} className="flex items-start justify-between gap-3 rounded-md bg-gray-950/60 px-3 py-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm text-gray-100"><span className="truncate">{x.name}</span><span className="text-[11px] font-semibold text-blue-300">{x.decision?.action || '待判断'}</span></div>
            <div className="mt-0.5 text-[11px] leading-4 text-gray-600">{x.decision?.summary || `领涨：${x.leader || '--'}`}</div>
          </div>
          <div className="shrink-0 text-right"><div className="text-sm font-semibold text-blue-300">{x.decision?.score ?? '--'}分</div><div className={`text-xs ${pctClass(x.pct_num)}`}>{x.pct || fmtPct(x.pct_num)}</div></div>
        </div>
      ))}
    </div>
  )
}

function SentimentGauge({ s }: { s?: MarketData['sentiment'] }) {
  if (!s) return null
  const colorMap: Record<string, { ring: string; text: string; bg: string }> = {
    red: { ring: 'border-red-500', text: 'text-red-400', bg: 'from-red-900/40' },
    orange: { ring: 'border-orange-500', text: 'text-orange-400', bg: 'from-orange-900/40' },
    gray: { ring: 'border-gray-500', text: 'text-gray-300', bg: 'from-gray-800/40' },
    cyan: { ring: 'border-cyan-500', text: 'text-cyan-400', bg: 'from-cyan-900/40' },
    blue: { ring: 'border-blue-500', text: 'text-blue-400', bg: 'from-blue-900/40' },
  }
  const c = colorMap[s.color || 'gray'] || colorMap.gray
  return (
    <div className={`flex items-center gap-5 rounded-xl border border-gray-800 bg-gradient-to-r ${c.bg} to-gray-900 px-5 py-4`}>
      <div className={`flex h-24 w-24 shrink-0 flex-col items-center justify-center rounded-full border-4 ${c.ring}`}>
        <span className="text-3xl leading-none">{s.emoji}</span>
        <span className={`mt-1 text-2xl font-bold leading-tight ${c.text}`}>{s.score ?? 0}</span>
        <span className="text-[10px] text-gray-500">情绪温度</span>
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-xl font-bold ${c.text}`}>{s.label}</span>
          <span className="text-xs text-gray-500">指数均值 {fmtPct(s.index_avg)}</span>
        </div>
        <p className="mt-1 text-sm text-gray-400">{s.desc}</p>
      </div>
    </div>
  )
}

function BreadthBar({ b }: { b?: MarketData['breadth'] }) {
  if (!b) return <div className="text-sm text-gray-500">暂无涨跌家数</div>
  const up = b.up ?? 0
  const flat = b.flat ?? 0
  const down = b.down ?? 0
  const total = up + flat + down || 1
  const upW = (up / total) * 100
  const flatW = (flat / total) * 100
  const downW = (down / total) * 100
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-xs">
        <span className="font-medium text-red-400">上涨 {up}</span>
        <span className="text-gray-500">平 {flat}</span>
        <span className="font-medium text-green-400">下跌 {down}</span>
      </div>
      <div className="flex h-4 overflow-hidden rounded bg-gray-800">
        <div className="flex h-full items-center justify-center bg-red-600/80" style={{ width: `${upW}%` }}>
          {upW > 12 && <span className="text-[10px] text-white">{Math.round(upW)}%</span>}
        </div>
        <div className="h-full bg-gray-600" style={{ width: `${flatW}%` }} />
        <div className="flex h-full items-center justify-center bg-green-600/80" style={{ width: `${downW}%` }}>
          {downW > 12 && <span className="text-[10px] text-white">{Math.round(downW)}%</span>}
        </div>
      </div>
      <div className="mt-2 flex gap-4 text-[11px] text-gray-500">
        <span>涨超5% <span className="text-red-400">{b.up_over5 ?? 0}</span></span>
        <span>跌超5% <span className="text-green-400">{b.down_over5 ?? 0}</span></span>
        <span>赚钱效应 <span className="text-gray-300">{b.up_ratio ?? 0}%</span></span>
      </div>
    </div>
  )
}

function DistributionChart({ dist }: { dist?: DistBin[] }) {
  if (!dist?.length) return <div className="text-sm text-gray-500">暂无涨跌幅分布</div>
  const max = Math.max(...dist.map(d => d.count), 1)
  return (
    <div className="space-y-1">
      {dist.slice().reverse().map(d => (
        <div key={d.label} className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-right text-[11px] text-gray-500">{d.label}</span>
          <div className="h-4 flex-1 overflow-hidden rounded bg-gray-800/60">
            <div className={`h-full rounded ${d.side === 'up' ? 'bg-red-600/70' : 'bg-green-600/70'}`} style={{ width: `${(d.count / max) * 100}%` }} />
          </div>
          <span className={`w-10 shrink-0 text-right text-[11px] ${d.side === 'up' ? 'text-red-400' : 'text-green-400'}`}>{d.count}</span>
        </div>
      ))}
    </div>
  )
}

function BoardBadge({ n }: { n: number }) {
  const base = 'inline-flex min-w-[30px] items-center justify-center rounded px-1.5 h-5 text-[11px] font-bold leading-none'
  if (n >= 7) return <span className={`${base} border border-red-400 bg-gradient-to-r from-red-700 to-pink-600 text-white`}>{n}板</span>
  if (n >= 5) return <span className={`${base} border border-red-500 bg-red-700 text-white`}>{n}板</span>
  if (n === 4) return <span className={`${base} bg-red-600 text-white`}>4板</span>
  if (n === 3) return <span className={`${base} bg-orange-600 text-white`}>3板</span>
  if (n === 2) return <span className={`${base} bg-orange-500 text-white`}>2板</span>
  return <span className={`${base} bg-gray-700 text-gray-300`}>首板</span>
}

function LadderView({ ladder }: { ladder?: LadderRow[] }) {
  if (!ladder?.length) return <div className="py-4 text-center text-xs text-gray-600">当日无涨停</div>
  return (
    <div className="space-y-2">
      {ladder.map(row => (
        <div key={row.height} className="flex items-start gap-2">
          <BoardBadge n={row.height} />
          <span className="mt-0.5 w-8 shrink-0 text-xs text-gray-500">×{row.count}</span>
          <div className="flex flex-wrap gap-1.5">
            {row.names.slice(0, 10).map(n => (
              <span key={n} className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-300">{n}</span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function CapPerfView({ tiers }: { tiers?: CapTier[] }) {
  if (!tiers?.length) return <div className="text-sm text-gray-500">暂无市值分层表现</div>
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-5">
      {tiers.map(t => (
        <div key={t.tier} className="rounded-lg border border-gray-800 bg-gray-950/50 p-3">
          <div className="mb-1 truncate text-[11px] text-gray-500">{t.tier}</div>
          <div className={`text-lg font-bold ${marketPctColor(t.avg_pct)}`}>{fmtPct(t.avg_pct)}</div>
          <div className="mt-1 text-[10px] text-gray-600">
            {t.up}涨 / {t.down}跌
          </div>
        </div>
      ))}
    </div>
  )
}

function MarketSectorList({ items, up }: { items?: SectorItem[]; up: boolean }) {
  if (!items?.length) return <div className="py-2 text-xs text-gray-600">暂无数据</div>
  return (
    <div className="space-y-1">
      {items.map(s => (
        <div key={s.name + s.type} className="flex items-center gap-2 text-xs">
          <span className="flex-1 truncate text-gray-200">{s.name}</span>
          <span className="rounded bg-gray-800 px-1 text-[10px] text-gray-500">{s.type}</span>
          {s.leader && <span className="max-w-[90px] truncate text-[10px] text-gray-600">{s.leader}</span>}
          <span className={`w-14 text-right font-mono ${up ? 'text-red-400' : 'text-green-400'}`}>{fmtPct(s.pct)}</span>
        </div>
      ))}
    </div>
  )
}

function RankTable({ items, kind }: { items?: Stock[]; kind: 'pct' | 'amount' | 'turnover' }) {
  if (!items?.length) return <div className="py-4 text-center text-xs text-gray-600">暂无榜单</div>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <tbody>
          {items.slice(0, 8).map((s, i) => (
            <tr key={s.symbol} className="border-b border-gray-800/60 last:border-0">
              <td className="w-8 px-2 py-1.5 text-gray-600">{i + 1}</td>
              <td className="px-2 py-1.5">
                <div className="font-medium text-gray-200">{s.name}</div>
                <div className="text-[11px] text-gray-600">{s.symbol}</div>
              </td>
              <td className="px-2 py-1.5 text-right text-gray-400">{s.price?.toFixed?.(2) ?? '--'}</td>
              <td className={`px-2 py-1.5 text-right font-mono ${marketPctColor(stockPct(s))}`}>
                {kind === 'amount'
                  ? `${s.amount_yi?.toFixed?.(1) ?? '--'}亿`
                  : kind === 'turnover'
                    ? `${s.turnover?.toFixed?.(1) ?? '--'}%`
                    : fmtPct(stockPct(s))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MarketInsightGrid({ insights }: { insights: DataInsight[] }) {
  if (!insights.length) return null
  const toneClass = (tone?: DataInsight['tone']) => {
    if (tone === 'red') return 'border-red-900/50 bg-red-950/15'
    if (tone === 'green') return 'border-emerald-900/50 bg-emerald-950/15'
    if (tone === 'amber') return 'border-amber-900/50 bg-amber-950/15'
    return 'border-blue-900/50 bg-blue-950/15'
  }
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950/45 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-bold text-white">当天数据结论</div>
          <div className="mt-0.5 text-xs text-gray-500">由涨跌家数、指数分化、涨停炸板、板块和榜单自动推导</div>
        </div>
        <span className="rounded bg-gray-800 px-2 py-1 text-[11px] text-gray-400">{insights.length} 条</span>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {insights.map((it, i) => (
          <div key={`${it.title}-${i}`} className={`rounded-lg border p-3 ${toneClass(it.tone)}`}>
            <div className="mb-2 flex items-start gap-2">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-gray-900 font-mono text-[10px] text-blue-200">{i + 1}</span>
              <div className="text-sm font-semibold leading-5 text-white">{it.title}</div>
            </div>
            <div className="text-xs leading-5 text-gray-400">
              <span className="text-gray-500">证据：</span>{it.evidence}
            </div>
            <div className="mt-1.5 text-xs leading-5 text-gray-300">
              <span className="text-gray-500">含义：</span>{it.meaning}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function MarketReviewBlock({ market, analysis, rankTab, setRankTab }: {
  market?: MarketData
  analysis?: string
  rankTab: 'gainers' | 'losers' | 'amount' | 'turnover'
  setRankTab: (tab: 'gainers' | 'losers' | 'amount' | 'turnover') => void
}) {
  if (!market) return null
  const ls = market.limit_stats || {}
  const breadth = market.breadth || {}
  const rankings = market.rankings || {}
  const sectors = market.sectors || {}
  const insights = buildMarketInsights(market)
  return (
    <ReviewSection index="01" title="市场复盘" aside="从原市场复盘整合到今日复盘">
      <div className="space-y-4">
        <MarketInsightGrid insights={insights} />
        <AnalysisMarkdown text={analysis} title="市场逻辑判断" />
        {market.summary && <p className="px-1 text-sm leading-relaxed text-gray-400">{market.summary}</p>}

        <div className="space-y-4">
          <SentimentGauge s={market.sentiment} />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Metric label="涨停" value={ls.zt_count ?? 0} tone="red" />
            <Metric label="跌停" value={ls.dt_count ?? 0} tone="green" />
            <Metric label="两市成交" value={`${Math.round(market.amount?.total_yi ?? 0)}亿`} />
            <Metric label="上涨" value={breadth.up ?? 0} tone="red" />
            <Metric label="下跌" value={breadth.down ?? 0} tone="green" />
            <Metric label="炸板" value={`${ls.broken_count ?? 0}只`} />
          </div>
        </div>

        {!!market.indices?.length && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {market.indices.map(idx => (
              <div key={idx.key || idx.name} className="rounded-lg border border-gray-800 bg-gray-950/50 px-3 py-2">
                <div className="text-[11px] text-gray-500">{idx.name}</div>
                <div className={`font-mono text-lg font-bold ${marketPctColor(idx.pct)}`}>{idx.price?.toFixed?.(2) ?? '--'}</div>
                <div className={`font-mono text-xs ${marketPctColor(idx.pct)}`}>{fmtPct(idx.pct)}</div>
              </div>
            ))}
          </div>
        )}

        <DetailBox title="市场数据拆解（涨跌分布 / 连板 / 榜单 / 要闻）">
          {market.ai_review && (
            <div className="rounded-lg border border-gray-800 bg-gray-950/45 p-3">
              <div className="mb-2 text-xs font-semibold text-indigo-300">AI 智能复盘点评</div>
              <div className="prose prose-invert prose-sm max-w-none text-gray-300 leading-relaxed prose-headings:mb-1.5 prose-headings:mt-3 prose-headings:text-sm prose-headings:font-bold prose-headings:text-indigo-300 prose-li:my-0.5 prose-p:my-1.5 prose-strong:text-white">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{market.ai_review}</ReactMarkdown>
              </div>
            </div>
          )}

        <Section title="涨跌家数"><BreadthBar b={market.breadth} /></Section>
        <Section title="涨跌幅分布"><DistributionChart dist={market.distribution} /></Section>

        <Section title="连板梯队" aside={`涨停 ${ls.zt_count ?? 0} · 最高 ${ls.max_continuity ?? 0} 板`}>
          <LadderView ladder={ls.ladder} />
        </Section>

        <Section title="涨停行业分布">
          {!!ls.zt_by_industry?.length ? (
            <div className="flex flex-wrap gap-2">
              {ls.zt_by_industry.map(it => (
                <span key={it.industry} className="rounded-full border border-red-800/50 bg-red-900/30 px-2.5 py-1 text-xs text-red-300">
                  {it.industry} <span className="font-bold text-red-400">{it.count}</span>
                </span>
              ))}
            </div>
          ) : <div className="py-4 text-center text-xs text-gray-600">无数据</div>}
          {!!ls.dt_stocks?.length && (
            <div className="mt-4 border-t border-gray-800 pt-3">
              <div className="mb-2 text-xs text-gray-500">跌停 {ls.dt_count ?? 0} 只</div>
              <div className="flex flex-wrap gap-1.5">
                {ls.dt_stocks.map(s => (
                  <span key={s.symbol} className="rounded border border-green-800/50 bg-green-900/30 px-2 py-0.5 text-xs text-green-300">
                    {s.name}{(s.dt_days ?? 1) > 1 && <span className="ml-0.5 text-green-500">{s.dt_days}连跌</span>}
                  </span>
                ))}
              </div>
            </div>
          )}
        </Section>

        <Section title="市值分层表现" aside="平均涨跌幅 · 红涨/绿跌">
          <CapPerfView tiers={market.cap_perf} />
        </Section>

        <Section title="🔥 领涨板块">
          <MarketSectorList items={sectors.top_up} up />
        </Section>
        <Section title="❄️ 领跌板块">
          <MarketSectorList items={sectors.top_down} up={false} />
        </Section>

        <Section
          title="个股榜单"
          right={
            <div className="flex gap-1">
              {([['gainers', '涨幅'], ['losers', '跌幅'], ['amount', '成交额'], ['turnover', '换手']] as const).map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => setRankTab(k)}
                  className={`rounded px-2.5 py-1 text-xs transition-colors ${rankTab === k ? 'bg-gray-700 text-white' : 'text-gray-500 hover:bg-gray-800 hover:text-gray-300'}`}
                >{label}</button>
              ))}
            </div>
          }
        >
          <RankTable
            items={rankings[rankTab]}
            kind={rankTab === 'amount' ? 'amount' : rankTab === 'turnover' ? 'turnover' : 'pct'}
          />
        </Section>

        {!!market.news?.length && (
          <Section title="📰 今日市场要闻" aside={`${market.news.length} 条`}>
            <div className="space-y-2.5">
              {market.news.map((n, i) => {
                const inner = (
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 shrink-0 font-mono text-[11px] text-gray-600">{String(i + 1).padStart(2, '0')}</span>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm leading-snug text-gray-200 transition-colors group-hover:text-blue-300">{n.title}</div>
                      {n.summary && <div className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-gray-500">{n.summary}</div>}
                      <div className="mt-1 flex items-center gap-2 text-[10px] text-gray-600">
                        {n.source && <span className="rounded bg-gray-800 px-1.5 py-0.5 text-gray-400">{n.source}</span>}
                        {n.published && <span>{n.published}</span>}
                      </div>
                    </div>
                  </div>
                )
                return n.url ? (
                  <a key={i} href={n.url} target="_blank" rel="noreferrer" className="group block border-b border-gray-800/60 pb-2.5 last:border-0 last:pb-0">{inner}</a>
                ) : (
                  <div key={i} className="group block border-b border-gray-800/60 pb-2.5 last:border-0 last:pb-0">{inner}</div>
                )
              })}
            </div>
          </Section>
        )}
        </DetailBox>
      </div>
    </ReviewSection>
  )
}

function CalendarPicker({
  selected,
  today,
  dates,
  open,
  month,
  generating,
  canGenerateToday,
  onOpenChange,
  onSelect,
  onMonthChange,
  onGenerate,
}: {
  selected: string
  today: string
  dates: DateRow[]
  open: boolean
  month: Date
  generating: boolean
  canGenerateToday: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (date: string) => void
  onMonthChange: (month: Date) => void
  onGenerate: (date: string) => void
}) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const existing = useMemo(() => new Set(dates.map(d => d.date)), [dates])
  const year = month.getFullYear()
  const monthIndex = month.getMonth()
  const first = new Date(year, monthIndex, 1)
  const startPad = first.getDay()
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate()
  const cells: { date: string | null; day: number | null }[] = []
  for (let i = 0; i < startPad; i++) cells.push({ date: null, day: null })
  for (let d = 1; d <= daysInMonth; d++) {
    const date = ymd(new Date(year, monthIndex, d))
    cells.push({ date, day: d })
  }
  while (cells.length % 7 !== 0) cells.push({ date: null, day: null })

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) onOpenChange(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open, onOpenChange])

  const isWeekend = (date: string) => {
    const dow = dateFromYmd(date).getDay()
    return dow === 0 || dow === 6
  }

  const handleDayClick = (date: string) => {
    if (isWeekend(date) || date > today) return
    if (existing.has(date)) onSelect(date)
    else if (date === today && !canGenerateToday) onSelect(date)
    else onGenerate(date)
    onOpenChange(false)
  }

  return (
    <div ref={wrapperRef} className="relative">
      <button
        onClick={() => onOpenChange(!open)}
        className="flex min-w-[160px] items-center gap-2 rounded border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-700"
      >
        <span>📅</span>
        <span className="font-mono">{selected}</span>
        {existing.has(selected) && <span className="text-[10px] text-green-400">●</span>}
        <span className="ml-auto text-gray-500">▾</span>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-[280px] rounded-xl border border-gray-700 bg-gray-900 p-3 shadow-2xl">
          <div className="mb-2 flex items-center justify-between">
            <button
              onClick={() => onMonthChange(new Date(year, monthIndex - 1, 1))}
              className="rounded p-1 text-gray-400 hover:bg-gray-800 hover:text-white"
            >‹</button>
            <span className="text-sm font-semibold text-white">{year}年{monthIndex + 1}月</span>
            <button
              onClick={() => onMonthChange(new Date(year, monthIndex + 1, 1))}
              className="rounded p-1 text-gray-400 hover:bg-gray-800 hover:text-white"
            >›</button>
          </div>

          <div className="mb-1 grid grid-cols-7 gap-1">
            {['日', '一', '二', '三', '四', '五', '六'].map((x, i) => (
              <div key={x} className={`text-center text-[10px] font-medium ${i === 0 || i === 6 ? 'text-gray-600' : 'text-gray-400'}`}>{x}</div>
            ))}
          </div>

          <div className="grid grid-cols-7 gap-1">
            {cells.map((cell, idx) => {
              if (!cell.date) return <div key={`blank-${idx}`} />
              const date = cell.date
              const isSelected = selected === date
              const isToday = today === date
              const hasData = existing.has(date)
              const disabled = date > today || isWeekend(date)
              const baseCls = 'relative flex h-8 items-center justify-center rounded text-xs font-mono transition-colors'
              if (disabled) {
                return <div key={date} className={`${baseCls} text-gray-700`}>{cell.day}</div>
              }
              if (hasData) {
                return (
                  <button
                    key={date}
                    onClick={() => handleDayClick(date)}
                    className={`${baseCls} ${isSelected ? 'bg-blue-600 text-white' : 'bg-green-900/50 text-green-300 hover:bg-green-800/70'} ${isToday ? 'ring-1 ring-amber-400' : ''}`}
                    title={`${date} 已有数据，点击查看`}
                  >
                    {cell.day}
                    <span className="absolute bottom-0.5 right-1 h-1 w-1 rounded-full bg-green-400" />
                  </button>
                )
              }
              return (
                <button
                  key={date}
                  onClick={() => handleDayClick(date)}
                  disabled={generating}
                  className={`${baseCls} ${isSelected ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-500 hover:bg-red-900/40 hover:text-red-300'} ${isToday ? 'ring-1 ring-amber-400' : ''} ${generating ? 'cursor-wait opacity-40' : ''}`}
                  title={isToday && !canGenerateToday ? '今日尚未收盘，15:10后才能生成日档案' : (isToday ? '今日待生成，点击触发' : `${date} 暂无数据，点击触发后台生成`)}
                >
                  {cell.day}
                </button>
              )
            })}
          </div>

          <div className="mt-3 flex items-center gap-3 border-t border-gray-800 pt-2 text-[10px] text-gray-500">
            <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded border border-green-700 bg-green-900/50" />已有</span>
            <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded border border-gray-700 bg-gray-800" />未生成</span>
            <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-blue-600" />当前</span>
          </div>
          <p className="mt-1.5 text-[10px] leading-relaxed text-gray-600">点已有档案查看 · 历史缺档可手动补齐 · 当日15:10后生成</p>
        </div>
      )}
    </div>
  )
}

export default function TodayReviewPage() {
  const watchlist = useWatchlist()
  const [dates, setDates] = useState<DateRow[]>([])
  const [selected, setSelected] = useState(todayStr())
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [calendarMonth, setCalendarMonth] = useState(dateFromYmd(todayStr()))
  const [data, setData] = useState<TodayReview | null>(null)
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState<{ running?: boolean; progress?: string }>({})
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [requestedDates, setRequestedDates] = useState<Set<string>>(() => new Set())
  const [rankTab, setRankTab] = useState<'gainers' | 'losers' | 'amount' | 'turnover'>('gainers')

  const watchPayload = useMemo(
    () => watchlist.map(x => ({ code: x.code, name: x.name || '', date: x.date || '' })),
    [watchlist],
  )

  async function loadDates() {
    const r = await fetch('/api/today-review/dates')
    const d = await r.json()
    const rows = d.dates ?? []
    setDates(rows)
  }

  async function loadDaily(date: string) {
    setLoading(true)
    try {
      const r = await fetch(`/api/today-review/daily?date=${date}`)
      const d = await r.json()
      setData(d.data ?? null)
      setMessage(d.message ?? '')
    } finally {
      setLoading(false)
    }
  }

  async function generate(date = selected) {
    const r = await fetch('/api/today-review/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date, watchlist: watchPayload }),
    })
    const d = await r.json()
    setMessage(d.message ?? '')
    setStatus(d.status ?? {})
    if (d.market_status) setMarketStatus(d.market_status)
  }

  useEffect(() => {
    Promise.all([
      fetch('/api/trading-day/status').then(r => r.json()),
      fetch('/api/today-review/dates').then(r => r.json()),
    ]).then(([clock, archive]) => {
      const rows = (archive.dates ?? []) as DateRow[]
      setMarketStatus(clock as MarketStatus)
      setDates(rows)
      if (clock.phase === 'postmarket') {
        setSelected(clock.today)
      } else {
        const completed = rows.some(row => row.date === clock.completed_trade_date)
          ? clock.completed_trade_date
          : rows[0]?.date
        if (completed) setSelected(completed)
      }
    }).catch(() => {
      loadDates().catch(() => {})
    })
  }, [])

  useEffect(() => {
    loadDaily(selected).catch(() => {})
    setCalendarMonth(dateFromYmd(selected))
  }, [selected])

  useEffect(() => {
    const canAutoGenerate = marketStatus?.can_generate_postmarket && selected === marketStatus.today
    if (canAutoGenerate && !loading && !data && message && !status.running && !requestedDates.has(selected)) {
      setRequestedDates(prev => new Set(prev).add(selected))
      generate(selected).catch(() => {})
    }
  }, [selected, loading, data, message, status.running, requestedDates, marketStatus])

  useEffect(() => {
    if (!status.running) return
    const t = window.setInterval(async () => {
      const r = await fetch('/api/today-review/status')
      const s = await r.json()
      if (s.market_status) setMarketStatus(s.market_status)
      setStatus(s)
      if (!s.running && status.running) {
        await loadDates()
        await loadDaily(selected)
      }
    }, 2500)
    return () => window.clearInterval(t)
  }, [selected, status.running])

  const m = data?.market
  const p = data?.portfolio
  const w = data?.watchlist
  const ind = data?.industry
  const intl = data?.international
  const a = data?.analysis

  return (
    <main className="mx-auto max-w-7xl px-4 py-5">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="text-xs text-gray-500">盘后闭环</div>
          <h1 className="mt-1 text-2xl font-bold text-white">盘后日档案</h1>
          <div className="mt-1 text-sm text-gray-500">
            {data
              ? `${data.trade_date} · ${fmtTime(data.generated_at)} 保存`
              : selected === marketStatus?.today && !marketStatus.can_generate_postmarket
                ? '交易尚未闭环，当日日档案将在15:10后生成'
                : message || '读取中...'}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <CalendarPicker
            selected={selected}
            today={todayStr()}
            dates={dates}
            open={calendarOpen}
            month={calendarMonth}
            generating={!!status.running}
            canGenerateToday={!!marketStatus?.can_generate_postmarket}
            onOpenChange={setCalendarOpen}
            onMonthChange={setCalendarMonth}
            onSelect={date => {
              setSelected(date)
            }}
            onGenerate={date => {
              setSelected(date)
              generate(date).catch(() => {})
            }}
          />
          <button
            onClick={() => generate(selected)}
            disabled={!!status.running || (selected === marketStatus?.today && !marketStatus?.can_generate_postmarket)}
            className="inline-flex h-8 items-center gap-2 rounded bg-red-600 px-3 text-sm font-medium text-white transition-colors hover:bg-red-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-500"
            title={selected === marketStatus?.today && !marketStatus?.can_generate_postmarket ? '交易日15:10后才能生成当日日档案' : '重新生成当前日档案'}
          >
            <RefreshCw className={`h-4 w-4 ${status.running ? 'animate-spin' : ''}`} />
            {status.running ? '生成中' : '重新生成'}
          </button>
        </div>
      </div>

      {status.running && (
        <div className="mb-4 rounded-lg border border-blue-800 bg-blue-950/30 px-4 py-3 text-sm text-blue-200">
          {status.progress || '正在生成盘后日档案...'}
        </div>
      )}

      {!data && !status.running ? (
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-8 text-center text-gray-400">
          {loading ? '读取中...' : message || '暂无日档案'}
        </div>
      ) : data ? (
        <div className="space-y-4">
          <section className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
            <div className="grid gap-3 md:grid-cols-4">
              <Metric label="情绪温度" value={`${m?.sentiment?.score ?? 0}℃ ${m?.sentiment?.label ?? ''}`} tone="blue" />
              <Metric label="涨跌家数" value={`${m?.breadth?.up ?? 0} 涨 / ${m?.breadth?.down ?? 0} 跌`} tone="red" />
              <Metric label="持仓今日盈亏" value={`${Number(p?.summary?.today_pnl ?? 0) >= 0 ? '+' : ''}${fmtMoney(p?.summary?.today_pnl)}`} tone={Number(p?.summary?.today_pnl ?? 0) >= 0 ? 'red' : 'green'} />
              <Metric label="自选表现" value={`${w?.summary?.count ?? 0} 只 · ${fmtPct(w?.summary?.avg_pct)}`} tone={Number(w?.summary?.avg_pct ?? 0) >= 0 ? 'red' : 'green'} />
            </div>
            <p className="mt-3 text-sm leading-6 text-gray-300">{m?.summary}</p>
          </section>

          <MarketRadarEvaluation tradeDate={data.trade_date} />

          <MarketReviewBlock market={m} analysis={a?.market_review} rankTab={rankTab} setRankTab={setRankTab} />

          <ReviewSection index="02" title="持仓复盘" aside="账户盈亏、逐只持仓逻辑、风险动作">
            <div className="space-y-3">
              <AnalysisMarkdown text={a?.portfolio_review} title="持仓逻辑判断" />
              <p className="text-sm leading-6 text-gray-300">{p?.conclusion}</p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Metric label="总市值" value={fmtMoney(p?.summary?.total_value)} />
              <Metric label="总浮盈亏" value={`${Number(p?.summary?.total_pnl_amount ?? 0) >= 0 ? '+' : ''}${fmtMoney(p?.summary?.total_pnl_amount)} · ${fmtPct(p?.summary?.total_pnl_pct)}`} tone={Number(p?.summary?.total_pnl_amount ?? 0) >= 0 ? 'red' : 'green'} />
            </div>
            {!!p?.positions?.length && (
              <div className="mt-3">
                <div className="mb-2 text-xs font-medium text-gray-400">持仓逐只拆解</div>
                <StockList items={p.positions} empty="暂无持仓明细" />
              </div>
            )}
            {!!p?.alerts?.length && (
              <div className="mt-3 space-y-2">
                {p.alerts.slice(0, 3).map((a, i) => (
                  <div key={i} className="rounded-md border border-amber-800/50 bg-amber-950/20 px-3 py-2 text-xs text-amber-200">{a.text}</div>
                ))}
              </div>
            )}
          </ReviewSection>

          <ReviewSection index="03" title="自选复盘" aside="明确裁决、该留该剔、次日动作">
            <div className="space-y-3">
              <WatchlistDecisionPanel items={w?.stocks?.length ? w.stocks : w?.top_winners} />
              <WatchlistExecutionPlan items={w?.stocks?.length ? w.stocks : w?.top_winners} />
            </div>
          </ReviewSection>

          <ReviewSection index="04" title="行业板块复盘" aside="领涨领跌、主线轮动、持续性判断">
            <div className="space-y-3">
              <AnalysisMarkdown text={a?.industry_review} title="行业逻辑判断" />
              <p className="text-sm leading-6 text-gray-300">{ind?.conclusion}</p>
              <div>
                <div className="mb-2 text-xs font-medium text-gray-400">领涨方向</div>
                <IndustryList items={ind?.top_up} empty="暂无行业数据" />
              </div>
              <div>
                <div className="mb-2 text-xs font-medium text-gray-400">领跌方向</div>
                <IndustryList items={ind?.top_down} empty="暂无行业数据" />
              </div>
            </div>
          </ReviewSection>

          <ReviewSection index="05" title="国际形势复盘" aside="海外事件、风险偏好、A股映射方向">
            <div className="space-y-3">
              <AnalysisMarkdown text={a?.international_review} title="国际映射判断" />
              <p className="text-sm leading-6 text-gray-300">{intl?.conclusion}</p>
              <div className="space-y-2">
                {(intl?.items ?? []).slice(0, 5).map((x, i) => (
                  <div key={i} className="rounded-md bg-gray-950/60 px-3 py-2">
                    <div className="line-clamp-2 text-sm text-gray-100">{x.title}</div>
                    {x.summary && <div className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{x.summary}</div>}
                    <div className="mt-1 text-[11px] text-gray-500">影响评分 {x.impact_score ?? 0}</div>
                  </div>
                ))}
                {!intl?.items?.length && <div className="text-sm text-gray-500">暂无国际热点</div>}
              </div>
            </div>
          </ReviewSection>

          <ReviewSection index="06" title="风险与机会" aside="风险提示、机会线索、仓位警惕">
            <div className="space-y-3">
              <div>
                <div className="mb-2 text-xs font-medium text-emerald-300">风险</div>
                <ul className="space-y-2 text-sm text-gray-300">
                  {(data.risk_opportunity?.risks ?? ['暂无突出风险']).map((x, i) => <li key={i} className="rounded-md bg-gray-950/60 px-3 py-2">{x}</li>)}
                </ul>
              </div>
              <div>
                <div className="mb-2 text-xs font-medium text-red-300">机会</div>
                <ul className="space-y-2 text-sm text-gray-300">
                  {(data.risk_opportunity?.opportunities ?? ['暂无突出机会']).map((x, i) => <li key={i} className="rounded-md bg-gray-950/60 px-3 py-2">{x}</li>)}
                </ul>
              </div>
            </div>
          </ReviewSection>

          <ReviewSection index="07" title="明日关注" aside="次日开盘、主线延续、持仓自选动作">
            <ul className="space-y-2 text-sm text-gray-300">
              {(data.tomorrow_watch ?? []).length
                ? data.tomorrow_watch!.map((x, i) => <li key={i} className="rounded-md bg-gray-950/60 px-3 py-2">{x}</li>)
                : <li className="rounded-md bg-gray-950/60 px-3 py-2">暂无明确关注项</li>}
            </ul>
          </ReviewSection>
        </div>
      ) : null}
    </main>
  )
}
