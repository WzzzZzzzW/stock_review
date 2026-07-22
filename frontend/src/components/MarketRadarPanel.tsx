import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  ChevronRight,
  CircleDot,
  Clock3,
  Landmark,
  MessageCircleQuestion,
  Newspaper,
  Radar,
  ShieldAlert,
  Target,
} from 'lucide-react'
import { aiAssistantStore, type AssistantTargetType } from '../stores/aiAssistantStore'
import StockCapitalRanking from './StockCapitalRanking'

type Phase = 'premarket' | 'intraday'
type ResearchSection = 'market' | 'limitup' | 'lhb' | 'industry' | 'news'

interface SectorRow {
  name: string
  pct: number
  breadth: number
  net_in: number
  leader?: string
  score: number
  rank: number
  state: string
  tone: 'attack' | 'risk' | 'neutral'
  velocity?: number
  evidence?: string
}

interface RadarEvent {
  occurred_at?: string
  severity?: string
  category?: string
  title: string
  detail: string
  entity?: string
}

interface NewsEvent {
  title: string
  one_line?: string
  direction?: string
  hotness?: number
  published?: string
  sources?: string[]
  affected_sectors?: string[]
}

interface PersonalRow {
  symbol: string
  name: string
  kind: string
  pct_change: number
  industry: string
  sector_state: string
  sector_score?: number
  tone: 'attack' | 'risk' | 'neutral'
  action: string
  reason: string
}

interface AuctionCheck {
  time: string
  title: string
  detail: string
}

export interface MarketRadarData {
  phase?: Phase
  actual_phase?: string
  updated_at?: string
  comparison_at?: string
  error?: string
  market?: {
    avg_index_pct?: number
    index_dispersion?: number
    sector_up_ratio?: number
    decision?: { action?: string; score?: number; position_cap?: number; summary?: string }
  }
  rotation?: { attack?: SectorRow[]; risk?: SectorRow[]; neutral?: SectorRow[]; all?: SectorRow[] }
  capital?: { inflow?: SectorRow[]; outflow?: SectorRow[]; note?: string }
  changes?: RadarEvent[]
  timeline?: RadarEvent[]
  news?: NewsEvent[]
  personal?: {
    positions?: PersonalRow[]
    watchlist?: PersonalRow[]
    summary?: string
    risk_count?: number
    opportunity_count?: number
  }
  briefing?: {
    thesis?: string
    focus?: string
    avoid?: string
    personal?: string
    overnight?: NewsEvent[]
    auction_checks?: AuctionCheck[]
  }
}

interface Props {
  phase: Phase
  data: MarketRadarData | null
  loading?: boolean
  onOpenResearch?: (section: ResearchSection) => void
  onSelectStock?: (symbol: string, name: string) => void
}

function pctClass(value: number) {
  return value > 0 ? 'text-red-400' : value < 0 ? 'text-emerald-400' : 'text-gray-400'
}

function stateClass(tone: SectorRow['tone'] | PersonalRow['tone']) {
  if (tone === 'attack') return 'border-red-900/60 bg-red-950/20 text-red-300'
  if (tone === 'risk') return 'border-emerald-900/60 bg-emerald-950/20 text-emerald-300'
  return 'border-gray-700 bg-gray-800/60 text-gray-300'
}

function timeLabel(value?: string) {
  if (!value) return '--:--'
  const match = value.match(/(\d{2}:\d{2})(?::\d{2})?/)
  return match?.[1] || value
}

function newsTimeLabel(value?: string) {
  if (!value) return '时间未知'
  const localMatch = value.match(/^\d{4}-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/)
  if (localMatch) return `${localMatch[1]}-${localMatch[2]} ${localMatch[3]}:${localMatch[4]}`

  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed).replace(/\//g, '-')
}

function money(value: number) {
  return `${value > 0 ? '+' : ''}${Number(value || 0).toFixed(2)}亿`
}

function SectionHead({ icon: Icon, title, meta }: { icon: typeof Radar; title: string; meta?: string }) {
  return (
    <div className="flex flex-col gap-1 border-b border-gray-800 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-blue-400" />
        <h2 className="text-sm font-semibold text-white">{title}</h2>
      </div>
      {meta && <p className="text-xs text-gray-500">{meta}</p>}
    </div>
  )
}

function AskAiButton({ phase, type, name, data, question }: {
  phase: Phase
  type: AssistantTargetType
  name: string
  data?: Record<string, unknown>
  question?: string
}) {
  return (
    <button
      type="button"
      title={`向AI询问${name}`}
      aria-label={`向AI询问${name}`}
      onClick={() => aiAssistantStore.open({
        page: phase,
        phase,
        target: { type, name, data },
      }, question)}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-gray-600 hover:bg-blue-950/60 hover:text-blue-300"
    >
      <MessageCircleQuestion className="h-4 w-4" />
    </button>
  )
}

function sectorQuestion(row: SectorRow) {
  if (row.net_in > 0 && row.pct < 0) return `为什么${row.name}净流入${money(row.net_in)}，板块却下跌${Math.abs(row.pct).toFixed(2)}%？这笔流入是否有效？`
  if (row.net_in < 0 && row.pct > 0) return `为什么${row.name}上涨${row.pct.toFixed(2)}%，资金却净流出${Math.abs(row.net_in).toFixed(2)}亿？`
  return `请解释${row.name}当前为什么被判断为“${row.state}”，并告诉我这个判断是否可靠。`
}

function NewsRows({ rows, phase }: { rows: NewsEvent[]; phase: Phase }) {
  if (!rows.length) return <div className="px-4 py-5 text-sm text-gray-500">新闻缓存正在更新，下一次刷新后补充事件映射。</div>
  return (
    <div className="divide-y divide-gray-800">
      {rows.slice(0, 5).map((row, index) => (
        <div key={`${row.title}-${index}`} className="grid gap-2 px-4 py-3 sm:grid-cols-[1fr_auto_32px] sm:items-start">
          <div>
            <div className="text-sm font-medium leading-5 text-gray-200">{row.title}</div>
            <div className="mt-1 text-xs text-gray-600">
              {(row.sources || []).filter(Boolean).join(' / ') || '来源未知'} · {newsTimeLabel(row.published)}
            </div>
            {row.one_line && <div className="mt-1 text-xs leading-5 text-gray-500">{row.one_line}</div>}
            {!!row.affected_sectors?.length && <div className="mt-1 text-xs text-blue-300">映射：{row.affected_sectors.join(' · ')}</div>}
          </div>
          <div className={`text-xs ${row.direction === 'positive' ? 'text-red-400' : row.direction === 'negative' ? 'text-emerald-400' : 'text-gray-500'}`}>
            {row.direction === 'positive' ? '偏利多' : row.direction === 'negative' ? '偏利空' : '待验证'}
          </div>
          <AskAiButton phase={phase} type="news" name={row.title} data={{ ...row }} question={`这条消息对今天A股有什么真实影响？市场是否已经反应？`} />
        </div>
      ))}
    </div>
  )
}

function RotationTable({ rows, phase }: { rows: SectorRow[]; phase: Phase }) {
  if (!rows.length) return <div className="px-4 py-5 text-sm text-gray-500">暂无满足当前筛选条件的板块。</div>
  return (
    <div className="divide-y divide-gray-800">
      {rows.slice(0, 10).map(row => (
        <div key={row.name} className="grid gap-2 px-4 py-3 sm:grid-cols-[1fr_90px_90px_110px_1.5fr_32px] sm:items-center">
          <div className="flex min-w-0 items-center gap-2">
            <span className={`shrink-0 rounded border px-2 py-0.5 text-xs font-medium ${stateClass(row.tone)}`}>{row.state}</span>
            <div className="min-w-0"><div className="truncate text-sm font-medium text-white">{row.name}</div><div className="truncate text-xs text-gray-600">龙头 {row.leader || '--'}</div></div>
          </div>
          <div className={`text-sm font-semibold ${pctClass(row.pct)}`}>{row.pct > 0 ? '+' : ''}{row.pct.toFixed(2)}%</div>
          <div><div className="text-xs text-gray-600">上涨广度</div><div className="text-sm text-gray-300">{Math.round(row.breadth * 100)}%</div></div>
          <div><div className="text-xs text-gray-600">净流入</div><div className={`text-sm ${pctClass(row.net_in)}`}>{money(row.net_in)}</div></div>
          <div className="text-xs leading-5 text-gray-500"><span className="text-gray-400">综合评分 {row.score}分</span>{row.evidence ? ` · ${row.evidence.replace('评分', '较上次评分')}` : ` · 排名 ${row.rank}`}</div>
          <AskAiButton phase={phase} type="sector" name={row.name} data={{ ...row }} question={sectorQuestion(row)} />
        </div>
      ))}
    </div>
  )
}

function PersonalRows({ rows, phase }: { rows: PersonalRow[]; phase: Phase }) {
  if (!rows.length) return <div className="px-4 py-5 text-sm text-gray-500">当前没有可映射的个人标的。</div>
  return (
    <div className="divide-y divide-gray-800">
      {rows.slice(0, 10).map(row => (
        <div key={`${row.kind}-${row.symbol}`} className="grid gap-2 px-4 py-3 sm:grid-cols-[1fr_90px_130px_2fr_32px] sm:items-center">
          <div><div className="text-sm font-medium text-white">{row.name}</div><div className="text-xs text-gray-600">{row.symbol} · {row.industry}</div></div>
          <div className={pctClass(row.pct_change)}>{row.pct_change > 0 ? '+' : ''}{row.pct_change.toFixed(2)}%</div>
          <div><span className={`rounded border px-2 py-1 text-xs font-medium ${stateClass(row.tone)}`}>{row.sector_state}</span></div>
          <div className="text-sm leading-5 text-gray-400"><span className="mr-2 font-semibold text-blue-300">{row.action}</span>{row.reason}</div>
          <AskAiButton phase={phase} type="stock" name={row.name} data={{ ...row }} question={`${row.name}当前受到板块怎样的影响？结合它自身走势给我一个明确结论。`} />
        </div>
      ))}
    </div>
  )
}

export default function MarketRadarPanel({ phase, data, loading, onOpenResearch, onSelectStock }: Props) {
  const [rotationMode, setRotationMode] = useState<'attack' | 'risk' | 'all'>('attack')
  const [personalMode, setPersonalMode] = useState<'positions' | 'watchlist'>('positions')
  const rotationRows = useMemo(() => {
    if (rotationMode === 'risk') return data?.rotation?.risk || []
    if (rotationMode === 'all') return data?.rotation?.all || []
    return data?.rotation?.attack || []
  }, [data, rotationMode])
  const personalRows = personalMode === 'positions' ? data?.personal?.positions || [] : data?.personal?.watchlist || []
  const decision = data?.market?.decision
  const briefing = data?.briefing
  const criticalChange = (data?.changes || []).find(change => change.severity === 'critical')

  useEffect(() => {
    if (phase !== 'intraday' || !criticalChange || !('Notification' in window) || Notification.permission !== 'granted') return
    const key = `${criticalChange.occurred_at || ''}:${criticalChange.title}`
    if (localStorage.getItem('market_radar_last_notification') === key) return
    localStorage.setItem('market_radar_last_notification', key)
    try { new Notification(`市场雷达：${criticalChange.title}`, { body: criticalChange.detail, tag: 'market-radar-critical' }) } catch { /* ignore */ }
  }, [criticalChange, phase])

  if (loading && !data) {
    return <section className="mb-4 rounded border border-gray-800 bg-gray-900/50 px-4 py-6 text-sm text-gray-500">正在建立市场雷达...</section>
  }
  if (!data || data.error) {
    return <section className="mb-4 rounded border border-red-900/50 bg-red-950/20 px-4 py-4 text-sm text-red-300">{data?.error || '市场雷达暂未返回数据。'}</section>
  }

  return (
    <div className="mb-4 space-y-4">
      <section className="overflow-hidden rounded border border-blue-900/60 bg-gray-900/60">
        <SectionHead
          icon={Radar}
          title={phase === 'premarket' ? '盘前市场雷达' : '盘中市场雷达'}
          meta={`更新 ${data.updated_at || '--'}${data.comparison_at ? ` · 对比 ${timeLabel(data.comparison_at)}` : ' · 正在建立变化基线'}`}
        />
        <div className="grid gap-px bg-gray-800 sm:grid-cols-2 lg:grid-cols-4">
          <div className="relative bg-gray-900 px-4 py-3"><div className="absolute right-2 top-2"><AskAiButton phase={phase} type="market" name="市场状态" data={{ ...(decision || {}) }} question="当前市场状态为什么是这个结论？最有决策权的证据是什么？" /></div><div className="text-xs text-gray-500">市场状态</div><div className="mt-1 text-lg font-semibold text-blue-300">{decision?.action || '待确认'}</div><div className="text-xs text-gray-600">评分 {decision?.score ?? '--'} · 仓位上限 {decision?.position_cap ?? '--'}%</div></div>
          <div className="relative bg-gray-900 px-4 py-3"><div className="absolute right-2 top-2"><AskAiButton phase={phase} type="metric" name="指数平均" data={{ avg_index_pct: data.market?.avg_index_pct, index_dispersion: data.market?.index_dispersion }} question="指数平均和指数分化应该如何一起理解？今天真实的市场结构是什么？" /></div><div className="text-xs text-gray-500">指数平均</div><div className={`mt-1 text-lg font-semibold ${pctClass(data.market?.avg_index_pct || 0)}`}>{(data.market?.avg_index_pct || 0) > 0 ? '+' : ''}{(data.market?.avg_index_pct || 0).toFixed(2)}%</div><div className="text-xs text-gray-600">分化 {data.market?.index_dispersion ?? '--'}个百分点</div></div>
          <div className="relative bg-gray-900 px-4 py-3"><div className="absolute right-2 top-2"><AskAiButton phase={phase} type="metric" name="板块广度" data={{ sector_up_ratio: data.market?.sector_up_ratio }} question="今天的板块广度说明赚钱效应如何？它与指数表现是否一致？" /></div><div className="text-xs text-gray-500">板块广度</div><div className="mt-1 text-lg font-semibold text-white">{data.market?.sector_up_ratio ?? '--'}%</div><div className="text-xs text-gray-600">行业处于上涨状态</div></div>
          <div className="relative bg-gray-900 px-4 py-3"><div className="absolute right-2 top-2"><AskAiButton phase={phase} type="metric" name="个人映射" data={{ risk_count: data.personal?.risk_count, opportunity_count: data.personal?.opportunity_count, summary: data.personal?.summary }} question="当前市场变化具体会影响我的哪些持仓和自选？给出优先级。" /></div><div className="text-xs text-gray-500">个人映射</div><div className="mt-1 text-lg font-semibold text-white">{data.personal?.risk_count || 0} 风险 / {data.personal?.opportunity_count || 0} 机会</div><div className="text-xs text-gray-600">持仓与自选合并扫描</div></div>
        </div>
        <div className="border-t border-gray-800 px-4 py-3 text-sm leading-6 text-gray-300">{decision?.summary}</div>
        {criticalChange && <div className="border-t border-red-900/50 bg-red-950/20 px-4 py-2.5 text-sm text-red-200"><span className="mr-2 font-semibold">关键变化</span>{criticalChange.title}：{criticalChange.detail}</div>}
      </section>

      {phase === 'premarket' && briefing && (
        <>
          <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
            <SectionHead icon={Target} title="今日作战简报" meta="市场先行，再映射到个人标的" />
            <div className="grid gap-px bg-gray-800 sm:grid-cols-2 lg:grid-cols-4">
              <div className="bg-gray-900 px-4 py-3"><div className="text-xs text-gray-500">总判断</div><p className="mt-1 text-sm leading-6 text-gray-200">{briefing.thesis}</p></div>
              <div className="bg-gray-900 px-4 py-3"><div className="text-xs text-red-300">主攻方向</div><p className="mt-1 text-sm leading-6 text-gray-200">{briefing.focus}</p></div>
              <div className="bg-gray-900 px-4 py-3"><div className="text-xs text-emerald-300">明确回避</div><p className="mt-1 text-sm leading-6 text-gray-200">{briefing.avoid}</p></div>
              <div className="bg-gray-900 px-4 py-3"><div className="text-xs text-blue-300">对我的影响</div><p className="mt-1 text-sm leading-6 text-gray-200">{briefing.personal}</p></div>
            </div>
          </section>

          <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
            <SectionHead icon={Clock3} title="集合竞价确认" meta="不确认就取消，不把计划变成执念" />
            <div className="divide-y divide-gray-800">
              {(briefing.auction_checks || []).map(check => (
                <div key={check.time} className="grid gap-2 px-4 py-3 sm:grid-cols-[70px_160px_1fr] sm:items-center">
                  <div className="text-sm font-semibold text-amber-300">{check.time}</div>
                  <div className="text-sm font-medium text-white">{check.title}</div>
                  <div className="text-sm leading-5 text-gray-500">{check.detail}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
            <SectionHead icon={Newspaper} title="隔夜事件与A股映射" meta="消息必须经过盘面验证" />
            <NewsRows rows={briefing.overnight || []} phase={phase} />
          </section>
        </>
      )}

      {phase === 'intraday' && (
        <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
          <SectionHead icon={Activity} title="刚刚发生的变化" meta="只记录足以改变行动的状态变化" />
          <div className="divide-y divide-gray-800">
            {(data.timeline || []).slice(0, 8).map((event, index) => (
              <div key={`${event.occurred_at}-${event.title}-${index}`} className="grid gap-2 px-4 py-3 sm:grid-cols-[64px_160px_1fr] sm:items-start">
                <div className="text-xs text-gray-600">{timeLabel(event.occurred_at)}</div>
                <div className={`text-sm font-semibold ${event.severity === 'critical' ? 'text-red-300' : event.severity === 'important' ? 'text-amber-300' : 'text-blue-300'}`}>{event.title}</div>
                <div className="text-sm leading-5 text-gray-500">{event.detail}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
        <div className="flex flex-col gap-3 border-b border-gray-800 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2"><CircleDot className="h-4 w-4 text-blue-400" /><h2 className="text-sm font-semibold text-white">板块轮动阶段</h2></div>
          <div className="inline-flex self-start rounded border border-gray-700 bg-gray-900 p-0.5 text-xs">
            {([['attack', '进攻'], ['risk', '风险'], ['all', '全部']] as const).map(([key, label]) => (
              <button key={key} onClick={() => setRotationMode(key)} className={`h-7 rounded px-3 ${rotationMode === key ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'}`}>{label}</button>
            ))}
          </div>
        </div>
        <RotationTable rows={rotationRows} phase={phase} />
      </section>

      <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
        <SectionHead icon={Landmark} title="资金方向" meta={data.capital?.note} />
        <div className="grid gap-px bg-gray-800 lg:grid-cols-2">
          <div className="bg-gray-900">
            <div className="flex items-center gap-2 border-b border-gray-800 px-4 py-2 text-xs font-medium text-red-300"><ArrowUpRight className="h-4 w-4" />净流入靠前</div>
            <div className="divide-y divide-gray-800">{(data.capital?.inflow || []).slice(0, 10).map(row => <div key={row.name} className="flex items-center gap-3 px-4 py-2.5 text-sm"><span className="min-w-0 flex-1 truncate text-gray-300">{row.name} · {row.state}</span><span className={pctClass(row.net_in)}>{money(row.net_in)}</span><AskAiButton phase={phase} type="sector" name={row.name} data={{ ...row }} question={sectorQuestion(row)} /></div>)}</div>
          </div>
          <div className="bg-gray-900">
            <div className="flex items-center gap-2 border-b border-gray-800 px-4 py-2 text-xs font-medium text-emerald-300"><ArrowDownRight className="h-4 w-4" />净流出靠前</div>
            <div className="divide-y divide-gray-800">{(data.capital?.outflow || []).slice(0, 10).map(row => <div key={row.name} className="flex items-center gap-3 px-4 py-2.5 text-sm"><span className="min-w-0 flex-1 truncate text-gray-300">{row.name} · {row.state}</span><span className={pctClass(row.net_in)}>{money(row.net_in)}</span><AskAiButton phase={phase} type="sector" name={row.name} data={{ ...row }} question={sectorQuestion(row)} /></div>)}</div>
          </div>
        </div>
      </section>

      {phase === 'intraday' && <StockCapitalRanking onSelectStock={onSelectStock} />}

      {phase === 'intraday' && (
        <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
          <SectionHead icon={Newspaper} title="事件与盘面验证" meta="先看影响，再等资金和广度确认" />
          <NewsRows rows={data.news || []} phase={phase} />
        </section>
      )}

      <section className="overflow-hidden rounded border border-gray-800 bg-gray-900/50">
        <div className="flex flex-col gap-3 border-b border-gray-800 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2"><ShieldAlert className="h-4 w-4 text-blue-400" /><div><h2 className="text-sm font-semibold text-white">市场变化对我的影响</h2><p className="mt-0.5 text-xs text-gray-500">{data.personal?.summary}</p></div></div>
          <div className="inline-flex self-start rounded border border-gray-700 bg-gray-900 p-0.5 text-xs">
            <button onClick={() => setPersonalMode('positions')} className={`h-7 rounded px-3 ${personalMode === 'positions' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'}`}>持仓</button>
            <button onClick={() => setPersonalMode('watchlist')} className={`h-7 rounded px-3 ${personalMode === 'watchlist' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'}`}>自选</button>
          </div>
        </div>
        <PersonalRows rows={personalRows} phase={phase} />
      </section>

      <div className="flex flex-wrap gap-x-4 gap-y-2 border-y border-gray-800 px-1 py-3">
        <button onClick={() => onOpenResearch?.('market')} className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200">大盘证据<ChevronRight className="h-3.5 w-3.5" /></button>
        <button onClick={() => onOpenResearch?.('industry')} className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200">完整行业<ChevronRight className="h-3.5 w-3.5" /></button>
        <button onClick={() => onOpenResearch?.('news')} className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200">新闻证据<ChevronRight className="h-3.5 w-3.5" /></button>
        <button onClick={() => onOpenResearch?.('lhb')} className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200">龙虎榜<ChevronRight className="h-3.5 w-3.5" /></button>
        <button onClick={() => onOpenResearch?.('limitup')} className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200">涨停结构<ChevronRight className="h-3.5 w-3.5" /></button>
      </div>
    </div>
  )
}
