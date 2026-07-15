import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowLeft,
  BookOpenCheck,
  BriefcaseBusiness,
  ChevronRight,
  CircleAlert,
  Crosshair,
  ListChecks,
  RefreshCw,
  ShieldCheck,
  Target,
} from 'lucide-react'
import PortfolioPage from './PortfolioPage'
import { useWatchlist } from '../stores/watchlistStore'

type Phase = 'premarket' | 'intraday'

interface Props {
  phase: Phase
  onSelectStock?: (symbol: string, name: string) => void
  onOpenResearch?: (section: 'market' | 'limitup' | 'lhb' | 'industry' | 'news') => void
}

interface MarketStatus {
  phase: 'premarket' | 'intraday' | 'postmarket'
  label: string
  plan_for_date: string
  server_time: string
  is_market_open: boolean
}

interface Position {
  symbol: string
  name: string
  current_price: number
  pct_change: number
  buy_price: number
  quantity: number
  pnl_amount: number
  pnl_pct: number
  today_pnl: number
  stop_loss?: number
  target_price?: number
  at_stop_loss?: boolean
  near_stop_loss?: boolean
  at_target?: boolean
}

interface PortfolioData {
  positions: Position[]
  summary: {
    total_value: number
    total_pnl_amount: number
    total_pnl_pct: number
    today_pnl: number
    position_count: number
  }
  alerts?: { symbol: string; name: string; type: string; message: string }[]
  updated_at?: string
}

interface GuidanceEntry {
  status?: string
  data?: {
    decision?: string
    urgency?: string
    summary?: string
    reduce_pct?: number
    sell_price?: number
    stop_price?: number
    reasons?: string[]
    advice?: string
  }
}

interface RecommendedStock {
  symbol: string
  name: string
  price: number
  pct_change: number
  score: number
  strength?: string
  sector?: string
  catalyst_type?: string
  reasons?: string[]
  strategy?: string
  tags?: string[]
}

interface RecommendationData {
  stocks: RecommendedStock[]
  hot_themes?: string[]
  market_sentiment?: string
  updated_at?: string
  news_latest?: string
  date?: string
  error?: string
}

interface Quote {
  symbol: string
  name: string
  price: number
  pct_change: number
  amount?: number
  pre_market?: boolean
}

interface DailyReport {
  indices?: { key: string; name: string; price: number; pct: number }[]
  sentiment?: { level?: string; label?: string }
  sectors?: {
    top_up?: { name: string; pct: number; leader?: string }[]
    top_down?: { name: string; pct: number; leader?: string }[]
    up_count?: number
    down_count?: number
  }
  updated_at?: string
}

interface IndustryData {
  industries?: { name: string; pct: string; pct_num: number; leader: string; net_in?: string }[]
  updated_at?: string
}

const emptyPortfolio: PortfolioData = {
  positions: [],
  summary: { total_value: 0, total_pnl_amount: 0, total_pnl_pct: 0, today_pnl: 0, position_count: 0 },
}

function pctClass(value: number) {
  return value > 0 ? 'text-red-400' : value < 0 ? 'text-emerald-400' : 'text-gray-400'
}

function percent(value: number) {
  const safe = Number(value || 0)
  return `${safe > 0 ? '+' : ''}${safe.toFixed(2)}%`
}

function positionDecision(position: Position, saved?: GuidanceEntry) {
  const decision = saved?.status === 'done' ? saved.data?.decision : ''
  if (decision) {
    return {
      action: decision,
      detail: saved?.data?.summary || saved?.data?.advice || saved?.data?.reasons?.[0] || '按卖点诊断执行',
      danger: decision === '清仓' || decision === '减仓',
    }
  }
  if (position.at_stop_loss) return { action: '清仓', detail: `已触及止损价 ${position.stop_loss ?? '--'}，不延迟执行`, danger: true }
  if (position.at_target) return { action: '减仓50%', detail: `已达到目标价 ${position.target_price ?? '--'}，先兑现利润`, danger: false }
  if (position.near_stop_loss) return { action: '减仓30%', detail: '距离止损不足5%，先降低风险敞口', danger: true }
  if (position.pnl_pct <= -8) return { action: '减仓50%', detail: '累计回撤超过8%，当前仓位不再具备进攻性价比', danger: true }
  if (position.pnl_pct >= 15 && position.pct_change < 0) return { action: '减仓30%', detail: '已有利润垫但当日转弱，主动锁定部分收益', danger: false }
  if (position.pct_change <= -2) return { action: '减仓30%', detail: '当日弱于市场，先收缩仓位再验证承接', danger: true }
  return { action: '持有', detail: '趋势未触发退出条件，保留仓位并严格执行止损', danger: false }
}

function marketCommand(report: DailyReport | null, recommendation: RecommendationData | null) {
  const indexPcts = (report?.indices ?? []).map(x => Number(x.pct || 0))
  const avg = indexPcts.length ? indexPcts.reduce((sum, value) => sum + value, 0) / indexPcts.length : 0
  const sentiment = recommendation?.market_sentiment || report?.sentiment?.label || '中性'
  if (sentiment.includes('偏空') || avg <= -0.8) {
    return { label: '防守', cap: '仓位上限30%', action: '先处理弱持仓，不开无催化新仓', tone: 'green' as const }
  }
  if (sentiment.includes('偏多') || avg >= 0.35) {
    return { label: '进攻', cap: '仓位上限70%', action: '只做前三强催化，分两笔确认后进场', tone: 'red' as const }
  }
  return { label: '结构进攻', cap: '仓位上限50%', action: '聚焦强板块和强个股，弱势方向直接放弃', tone: 'blue' as const }
}

function SectionTitle({ icon: Icon, title, summary }: { icon: typeof Activity; title: string; summary: string }) {
  return (
    <div className="flex flex-col gap-1 border-b border-gray-800 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-blue-400" />
        <h2 className="text-sm font-semibold text-white">{title}</h2>
      </div>
      <p className="text-xs text-gray-500">{summary}</p>
    </div>
  )
}

function LoadingLine() {
  return <div className="px-4 py-6 text-sm text-gray-500">正在读取交易数据...</div>
}

export default function TradingWorkspacePage({ phase, onSelectStock, onOpenResearch }: Props) {
  const watchlist = useWatchlist()
  const [status, setStatus] = useState<MarketStatus | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioData>(emptyPortfolio)
  const [guidance, setGuidance] = useState<Record<string, GuidanceEntry>>({})
  const [recommendation, setRecommendation] = useState<RecommendationData | null>(null)
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [daily, setDaily] = useState<DailyReport | null>(null)
  const [industry, setIndustry] = useState<IndustryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [portfolioOpen, setPortfolioOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const quoteUrl = watchlist.length
        ? `/api/watchlist/batch?symbols=${watchlist.map(item => item.code).join(',')}`
        : ''
      const requests: Promise<Response>[] = [
        fetch('/api/trading-day/status'),
        fetch('/api/portfolio'),
        fetch('/api/portfolio/sell-guidance'),
        fetch(phase === 'premarket' ? '/api/recommend/tomorrow' : '/api/recommend/today'),
        fetch('/api/daily-report'),
      ]
      if (quoteUrl) requests.push(fetch(quoteUrl))
      if (phase === 'intraday') requests.push(fetch('/api/industry/summary'))
      const responses = await Promise.all(requests)
      const payloads = await Promise.all(responses.map(async response => response.ok ? response.json() : {}))
      setStatus(payloads[0] as MarketStatus)
      setPortfolio({ ...emptyPortfolio, ...payloads[1] } as PortfolioData)
      setGuidance((payloads[2]?.guidance ?? {}) as Record<string, GuidanceEntry>)
      setRecommendation(payloads[3] as RecommendationData)
      setDaily(payloads[4] as DailyReport)
      let cursor = 5
      if (quoteUrl) {
        setQuotes((payloads[cursor]?.stocks ?? []) as Quote[])
        cursor += 1
      } else {
        setQuotes([])
      }
      if (phase === 'intraday') setIndustry(payloads[cursor] as IndustryData)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '数据读取失败')
    } finally {
      setLoading(false)
    }
  }, [phase, watchlist])

  useEffect(() => {
    void load()
    if (phase !== 'intraday') return
    const timer = window.setInterval(() => void load(), 60_000)
    return () => window.clearInterval(timer)
  }, [load, phase])

  const command = useMemo(() => marketCommand(daily, recommendation), [daily, recommendation])
  const decisions = useMemo(
    () => portfolio.positions.map(position => ({ position, ...positionDecision(position, guidance[position.symbol]) })),
    [guidance, portfolio.positions],
  )
  const urgent = decisions.filter(item => item.action !== '持有')
  const candidates = (recommendation?.stocks ?? []).slice(0, 3)
  const watchRows = quotes
    .map(quote => ({ ...quote, item: watchlist.find(item => item.code === quote.symbol) }))
    .sort((a, b) => b.pct_change - a.pct_change)
    .slice(0, 6)

  if (portfolioOpen) {
    return (
      <div>
        <div className="sticky top-14 z-30 border-b border-gray-800 bg-gray-950/95 px-4 py-2 backdrop-blur">
          <button
            onClick={() => setPortfolioOpen(false)}
            className="mx-auto flex max-w-7xl items-center gap-2 text-sm text-blue-300 hover:text-blue-200"
          >
            <ArrowLeft className="h-4 w-4" />返回{phase === 'premarket' ? '盘前计划' : '盘中执行'}
          </button>
        </div>
        <PortfolioPage />
      </div>
    )
  }

  const isPremarket = phase === 'premarket'
  const title = isPremarket ? '盘前作战台' : '盘中执行台'
  const subtitle = isPremarket ? '开盘前只做计划，明确仓位、买点和退出条件' : '盘中只处理触发项，不临时发明交易理由'

  return (
    <main className="mx-auto max-w-7xl px-4 py-5">
      <header className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <span>{status?.label || (isPremarket ? '盘前准备' : '盘中交易')}</span>
            <span>·</span>
            <span>{status?.plan_for_date || '今日'}执行</span>
          </div>
          <h1 className="mt-1 text-2xl font-bold text-white">{title}</h1>
          <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex h-9 items-center gap-2 self-start rounded border border-gray-700 bg-gray-900 px-3 text-sm text-gray-300 hover:bg-gray-800 disabled:opacity-50 sm:self-auto"
          title="刷新当前阶段数据"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新
        </button>
      </header>

      {status && status.phase !== phase && (
        <div className="mb-4 flex items-center gap-2 border-l-2 border-amber-500 bg-amber-950/20 px-3 py-2 text-xs text-amber-200">
          <CircleAlert className="h-4 w-4 shrink-0" />当前实际阶段为“{status.label}”，这里展示的是手动打开的{isPremarket ? '盘前计划' : '盘中任务'}。
        </div>
      )}
      {error && <div className="mb-4 border-l-2 border-red-500 bg-red-950/20 px-3 py-2 text-sm text-red-300">{error}</div>}
      {recommendation?.error && (
        <div className="mb-4 flex items-center gap-2 border-l-2 border-red-500 bg-red-950/20 px-3 py-2 text-sm text-red-200">
          <CircleAlert className="h-4 w-4 shrink-0" />推荐引擎额度不足，本阶段不依据缺失信号开新仓。充值或更换 DeepSeek Key 后刷新恢复。
        </div>
      )}

      <section className="mb-4 overflow-hidden rounded border border-gray-800 bg-gray-900/70">
        <div className="grid gap-px bg-gray-800 md:grid-cols-[1.1fr_1fr_1.7fr]">
          <div className="bg-gray-900 px-4 py-4">
            <div className="text-xs text-gray-500">今日总指令</div>
            <div className={`mt-1 text-2xl font-bold ${command.tone === 'red' ? 'text-red-400' : command.tone === 'green' ? 'text-emerald-400' : 'text-blue-300'}`}>{command.label}</div>
          </div>
          <div className="bg-gray-900 px-4 py-4">
            <div className="text-xs text-gray-500">风险预算</div>
            <div className="mt-1 text-lg font-semibold text-white">{command.cap}</div>
          </div>
          <div className="bg-gray-900 px-4 py-4">
            <div className="text-xs text-gray-500">执行口径</div>
            <div className="mt-1 text-sm font-medium leading-6 text-gray-200">{command.action}</div>
          </div>
        </div>
      </section>

      <div className="space-y-4">
        <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
          <SectionTitle
            icon={isPremarket ? BookOpenCheck : ListChecks}
            title={isPremarket ? '持仓开盘计划' : '优先执行队列'}
            summary={isPremarket ? `${portfolio.summary.position_count} 只持仓，每只只有一个动作` : `${urgent.length} 项需要处理，按风险优先级执行`}
          />
          {loading ? <LoadingLine /> : decisions.length ? (
            <div className="divide-y divide-gray-800">
              {(isPremarket ? decisions : [...urgent, ...decisions.filter(item => item.action === '持有')]).map(({ position, action, detail, danger }) => (
                <button
                  key={position.symbol}
                  onClick={() => onSelectStock?.(position.symbol, position.name)}
                  className="grid w-full gap-2 px-4 py-3 text-left hover:bg-gray-800/50 sm:grid-cols-[1.2fr_0.7fr_0.8fr_2.4fr_auto] sm:items-center"
                >
                  <div>
                    <div className="text-sm font-medium text-white">{position.name}</div>
                    <div className="text-xs text-gray-600">{position.symbol}</div>
                  </div>
                  <div className={pctClass(position.pct_change)}>{percent(position.pct_change)}</div>
                  <div className={pctClass(position.pnl_pct)}>累计 {percent(position.pnl_pct)}</div>
                  <div className="text-sm leading-5 text-gray-400"><span className={`mr-2 font-semibold ${danger ? 'text-red-300' : 'text-blue-300'}`}>{action}</span>{detail}</div>
                  <ChevronRight className="hidden h-4 w-4 text-gray-600 sm:block" />
                </button>
              ))}
            </div>
          ) : (
            <div className="px-4 py-6 text-sm text-gray-500">当前没有持仓。先建立持仓，工作台才会生成逐只执行指令。</div>
          )}
          <div className="border-t border-gray-800 px-4 py-2.5">
            <button onClick={() => setPortfolioOpen(true)} className="inline-flex items-center gap-2 text-xs font-medium text-blue-300 hover:text-blue-200">
              <BriefcaseBusiness className="h-4 w-4" />管理持仓与记录买卖<ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </section>

        <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
          <SectionTitle
            icon={Crosshair}
            title={isPremarket ? '下一交易日攻击名单' : '盘中触发机会'}
            summary={candidates.length ? `只保留评分最高的 ${candidates.length} 只` : '没有满足条件的标的就空仓，不凑数'}
          />
          {loading ? <LoadingLine /> : candidates.length ? (
            <div className="divide-y divide-gray-800">
              {candidates.map((stock, index) => (
                <button
                  key={stock.symbol}
                  onClick={() => onSelectStock?.(stock.symbol, stock.name)}
                  className="grid w-full gap-2 px-4 py-3 text-left hover:bg-gray-800/50 sm:grid-cols-[42px_1fr_0.8fr_2fr_auto] sm:items-center"
                >
                  <div className="flex h-7 w-7 items-center justify-center rounded bg-blue-950 text-xs font-bold text-blue-300">{index + 1}</div>
                  <div>
                    <div className="text-sm font-semibold text-white">{stock.name}</div>
                    <div className="text-xs text-gray-600">{stock.symbol} · {stock.sector || '待归类'}</div>
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-amber-300">{stock.score}分</div>
                    <div className={pctClass(stock.pct_change)}>{percent(stock.pct_change)}</div>
                  </div>
                  <div>
                    <div className="text-sm leading-5 text-gray-300">{stock.strategy || stock.reasons?.[0] || '按计划分批进场'}</div>
                    <div className="mt-1 text-xs text-gray-600">{stock.catalyst_type || stock.tags?.join(' · ') || '量价与消息面共振'}</div>
                  </div>
                  <ChevronRight className="hidden h-4 w-4 text-gray-600 sm:block" />
                </button>
              ))}
            </div>
          ) : (
            <div className="px-4 py-6 text-sm text-gray-500">
              {recommendation?.error
                ? '推荐引擎当前不可用。明确结论：不依据缺失的AI信号开仓。'
                : '当前没有高质量候选。明确结论：不新开仓，把注意力放在已有持仓。'}
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
          <SectionTitle icon={Target} title="自选任务" summary={`${watchlist.length} 只自选，按当日强弱排序`} />
          {loading ? <LoadingLine /> : watchRows.length ? (
            <div className="divide-y divide-gray-800">
              {watchRows.map((quote, index) => {
                const action = quote.pct_change >= 3 ? '保留强势' : quote.pct_change <= -2 ? '移出候选' : '等待突破'
                return (
                  <button
                    key={quote.symbol}
                    onClick={() => onSelectStock?.(quote.symbol, quote.name || quote.item?.name || quote.symbol)}
                    className="grid w-full grid-cols-[34px_1fr_auto] items-center gap-3 px-4 py-3 text-left hover:bg-gray-800/50 sm:grid-cols-[34px_1.2fr_0.8fr_2fr_auto]"
                  >
                    <span className="text-xs text-gray-600">{index + 1}</span>
                    <div><div className="text-sm font-medium text-white">{quote.name || quote.item?.name || quote.symbol}</div><div className="text-xs text-gray-600">{quote.symbol}</div></div>
                    <div className={pctClass(quote.pct_change)}>{percent(quote.pct_change)}</div>
                    <div className="hidden text-sm text-gray-400 sm:block"><span className="font-medium text-blue-300">{action}</span> · {quote.pct_change >= 3 ? '强于普通波动，等待回踩确认' : quote.pct_change <= -2 ? '当日明显转弱，不占用观察名额' : '尚未形成可交易优势'}</div>
                    <ChevronRight className="hidden h-4 w-4 text-gray-600 sm:block" />
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="px-4 py-6 text-sm text-gray-500">自选池为空。研究个股时加入自选，之后会在三个阶段自动进入任务清单。</div>
          )}
        </section>

        <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
          <SectionTitle icon={Activity} title={isPremarket ? '开盘证据' : '市场脉搏'} summary="这里只给结论，完整数据下沉到研究工具" />
          <div className="grid gap-px bg-gray-800 sm:grid-cols-2 lg:grid-cols-4">
            {(daily?.indices ?? []).slice(0, 4).map(index => (
              <div key={index.key} className="bg-gray-900 px-4 py-3">
                <div className="text-xs text-gray-500">{index.name}</div>
                <div className="mt-1 flex items-baseline justify-between gap-2">
                  <span className="text-sm font-semibold text-white">{index.price || '--'}</span>
                  <span className={`text-sm ${pctClass(index.pct)}`}>{percent(index.pct)}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="grid gap-3 px-4 py-3 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-xs font-medium text-red-300">强势方向</div>
              <p className="text-sm leading-6 text-gray-300">
                {(industry?.industries ?? daily?.sectors?.top_up ?? []).slice(0, 4).map(item => `${item.name} ${'pct_num' in item ? percent(item.pct_num) : percent(item.pct)}`).join(' · ') || '暂无可验证的强势板块'}
              </p>
            </div>
            <div>
              <div className="mb-2 text-xs font-medium text-emerald-300">回避方向</div>
              <p className="text-sm leading-6 text-gray-300">
                {(daily?.sectors?.top_down ?? []).slice(0, 4).map(item => `${item.name} ${percent(item.pct)}`).join(' · ') || '暂无可验证的弱势板块'}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-2 border-t border-gray-800 px-4 py-2.5">
            <button onClick={() => onOpenResearch?.('market')} className="text-xs text-blue-300 hover:text-blue-200">查看大盘证据</button>
            <button onClick={() => onOpenResearch?.('industry')} className="text-xs text-blue-300 hover:text-blue-200">查看行业证据</button>
            <button onClick={() => onOpenResearch?.('news')} className="text-xs text-blue-300 hover:text-blue-200">查看新闻证据</button>
            <button onClick={() => onOpenResearch?.('lhb')} className="text-xs text-blue-300 hover:text-blue-200">查看龙虎榜</button>
          </div>
        </section>
      </div>

      <footer className="mt-4 flex items-start gap-2 text-xs leading-5 text-gray-600">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
        <span>工作台给出单一执行结论；真正下单前仍以止损价、触发条件和可承受亏损为硬约束。数据更新时间：{portfolio.updated_at || recommendation?.updated_at || daily?.updated_at || '--'}。</span>
      </footer>
    </main>
  )
}
