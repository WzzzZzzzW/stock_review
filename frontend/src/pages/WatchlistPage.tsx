/**
 * 自选 & 推荐
 * Tab1: 我的自选 — 每分钟刷新行情
 * Tab2: 今日推荐 — 盘中实时可入，5分钟缓存，多因子评分
 * Tab3: 明日推荐 — 收盘后预判，结合今日走势+技术+资金
 */
import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import StockSearch from '../components/StockSearch'
import WatchlistButton from '../components/WatchlistButton'
import { watchlistStore, useWatchlist } from '../stores/watchlistStore'

// ── Types ─────────────────────────────────────────────────────────────────────

interface StockQuote {
  symbol: string; name: string; price: number; pct_change: number
  change_amount?: number; volume?: number; amount?: number
  high?: number; low?: number; open?: number
  pre_market?: boolean; prev_close?: number; not_found?: boolean
}

interface BatchResponse { stocks: StockQuote[]; updated_at: string }

interface RecommendStock {
  symbol: string; name: string; price: number; pct_change: number
  score: number; max_score: number
  reasons: string[]
  strategy: string
  catalyst_type?: string
  strength?: string      // 强/中/弱
  sector?: string
  tags: string[]
  // v2 fields (optional)
  breakdown?: { momentum?: number; day_quality?: number; technical: number; theme: number; capital: number }
  technical?: { ma5: number; ma20: number; ma60: number; rsi: number; close: number }
  rule_hits?: { direction: string; note: string; rule: string; confidence: number }[]
  news_time?: string     // 触发该股的新闻发布时间 HH:MM
}

interface RecommendResponse {
  stocks: RecommendStock[]; updated_at?: string; date: string; cached: boolean
  hot_themes?: string[]
  market_sentiment?: string
  news_latest?: string   // 消息面截止时间（最新一条新闻 HH:MM）
}

interface HistoryRecord {
  trade_date: string; mode: string; symbol: string; name: string
  first_seen: string; last_seen: string; appear_count: number
  peak_score: number; score: number; price: number; pct_change: number
  catalyst_type: string; strength: string; sector: string; news_time: string
  reasons: string[]; strategy: string
  rule_hits?: { direction: string; note: string; rule: string; confidence: number }[]
  tags?: string[]
}
interface HistoryResponse {
  history: HistoryRecord[]; count: number
  dates: { date: string; count: number }[]
  stats: { total_records: number; total_days: number }
}

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
  /** 受控视图：由 App 顶层子tab 传入（我的自选/今日推荐/明日预判/推荐历史）。
   *  传入时隐藏页内 tab 行；不传则回退到页内自带 tab（向后兼容）。*/
  view?: 'watchlist' | 'today' | 'tomorrow' | 'history'
}

// ── Constants ─────────────────────────────────────────────────────────────────
const LS_NOTIFY_DATE = 'watchlist_notify_date'

// 自选列表存储已迁到 watchlistStore（带加入日期、跨页面共享）

// 加入日期 YYYY-MM-DD → 分组标题「6.17 自选」；'' 为迁移来的旧数据
function dateLabel(d: string): string {
  if (!d) return '更早加入'
  const parts = d.split('-')
  if (parts.length < 3) return d
  return `${Number(parts[1])}.${Number(parts[2])} 自选`
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function pctColor(v: number) { return v > 0 ? 'text-red-400' : v < 0 ? 'text-emerald-400' : 'text-gray-400' }
function pctBg(v: number) {
  if (v > 3) return 'bg-red-600'; if (v > 0) return 'bg-red-900/40'
  if (v < -3) return 'bg-emerald-700'; if (v < 0) return 'bg-emerald-900/40'
  return 'bg-gray-800'
}
function fmtPct(v: number) { return `${v > 0 ? '+' : ''}${v.toFixed(2)}%` }
function fmtAmt(v: number) {
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`
  return String(v)
}

function scoreRingColor(s: number) {
  if (s >= 70) return '#22c55e'  // green-500
  if (s >= 50) return '#eab308'  // yellow-500
  return '#6b7280'               // gray-500
}

async function requestNotify(): Promise<boolean> {
  if (!('Notification' in window)) return false
  if (Notification.permission === 'granted') return true
  return (await Notification.requestPermission()) === 'granted'
}
function sendNotify(title: string, body: string) {
  if (Notification.permission !== 'granted') return
  try { new Notification(title, { body, icon: '/favicon.ico', tag: 'watchlist-daily' }) } catch { /* ignore */ }
}

// ── Quote Card ────────────────────────────────────────────────────────────────
function QuoteCard({ stock, onSelect, onRemove }: {
  stock: StockQuote; onSelect: () => void; onRemove: () => void
}) {
  if (stock.not_found) return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex items-center justify-between">
      <span className="text-gray-500 font-mono text-sm">{stock.symbol} <span className="text-gray-700">未找到</span></span>
      <button onClick={onRemove} className="text-gray-700 hover:text-red-400 text-lg">×</button>
    </div>
  )

  return (
    <div
      className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-600 transition-all cursor-pointer group"
      onClick={onSelect}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-white">{stock.name}</span>
            <span className="text-xs text-gray-600 font-mono">{stock.symbol}</span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xl font-bold text-white">{stock.price.toFixed(2)}</span>
            {stock.pre_market
              ? <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">昨收</span>
              : <span className={`text-sm font-semibold px-2 py-0.5 rounded ${pctBg(stock.pct_change)} ${pctColor(stock.pct_change)}`}>
                  {fmtPct(stock.pct_change)}
                </span>}
          </div>
        </div>
        <button
          onClick={e => { e.stopPropagation(); onRemove() }}
          className="text-gray-700 hover:text-red-400 text-lg opacity-0 group-hover:opacity-100 transition-opacity"
        >×</button>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        {[
          { label: '涨跌额', value: `${(stock.change_amount ?? 0) > 0 ? '+' : ''}${(stock.change_amount ?? 0).toFixed(2)}`, cls: pctColor(stock.pct_change) },
          { label: '成交额', value: fmtAmt(stock.amount ?? 0), cls: 'text-gray-300' },
          { label: '最高/最低', value: `${(stock.high ?? 0).toFixed(2)} / ${(stock.low ?? 0).toFixed(2)}`, cls: 'text-gray-300' },
        ].map(({ label, value, cls }) => (
          <div key={label}><p className="text-gray-600">{label}</p><p className={`font-mono ${cls}`}>{value}</p></div>
        ))}
      </div>
      <p className="text-xs text-blue-500 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">点击查看复盘 →</p>
    </div>
  )
}

// ── Score Ring ────────────────────────────────────────────────────────────────
function ScoreRing({ score, max = 100 }: { score: number; max?: number }) {
  const r = 20; const circ = 2 * Math.PI * r
  const fill = circ * (1 - score / max)
  return (
    <svg width="56" height="56" viewBox="0 0 56 56" className="shrink-0">
      <circle cx="28" cy="28" r={r} fill="none" stroke="#1f2937" strokeWidth="5" />
      <circle
        cx="28" cy="28" r={r} fill="none"
        stroke={scoreRingColor(score)} strokeWidth="5"
        strokeDasharray={circ} strokeDashoffset={fill}
        strokeLinecap="round"
        transform="rotate(-90 28 28)"
        style={{ transition: 'stroke-dashoffset 0.6s ease' }}
      />
      <text x="28" y="33" textAnchor="middle" fontSize="13" fontWeight="700"
        fill={scoreRingColor(score)}>{score.toFixed(0)}</text>
    </svg>
  )
}

// ── Strength Badge ────────────────────────────────────────────────────────────
function StrengthBadge({ s }: { s?: string }) {
  if (!s) return null
  const cls = s === '强' ? 'bg-red-900/60 text-red-300 border-red-700/60'
            : s === '中' ? 'bg-amber-900/50 text-amber-300 border-amber-700/50'
            : 'bg-gray-800 text-gray-400 border-gray-700'
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${cls}`}>
      {s}催化
    </span>
  )
}

// ── 脑库规则命中样式 ───────────────────────────────────────────────────────────
const ruleChipCls = (d: string) =>
  d === '利好' ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40'
  : d === '规避' ? 'bg-red-900/40 text-red-300 border-red-700/40'
  : 'bg-amber-900/30 text-amber-300 border-amber-700/40'

function RuleHitChips({ hits }: { hits: NonNullable<RecommendStock['rule_hits']> }) {
  return (
    <div className="flex flex-wrap gap-1">
      {hits.map((h, i) => (
        <span key={i}
          className={`text-[10px] px-1.5 py-0.5 rounded border ${ruleChipCls(h.direction)}`}>
          🧠 {h.note || h.rule.slice(0, 12)}
        </span>
      ))}
    </div>
  )
}

// ── Recommend Card ────────────────────────────────────────────────────────────
function RecommendCard({ stock, onSelect }: {
  stock: RecommendStock; onSelect: () => void
}) {
  const [expanded, setExpanded] = useState(false)

  // 🧠 脑库规则命中单独成块展示，从通用 reasons 里剔除，避免重复/错配颜色
  const warns    = stock.reasons.filter(r => r.startsWith('⚠️'))
  const positives = stock.reasons.filter(r => !r.startsWith('⚠️') && !r.startsWith('🧠'))
  const ruleHits  = stock.rule_hits ?? []

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden hover:border-gray-600 transition-all">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 cursor-pointer" onClick={() => setExpanded(e => !e)}>
        <ScoreRing score={stock.score} max={100} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-semibold text-white">{stock.name}</span>
            <span className="text-xs text-gray-600 font-mono">{stock.symbol}</span>
            <StrengthBadge s={stock.strength} />
            {stock.sector && (
              <span className="text-[10px] bg-purple-900/40 text-purple-300 border border-purple-800/40 px-1.5 py-0.5 rounded">
                {stock.sector}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-base font-bold text-white">{stock.price.toFixed(2)}</span>
            <span className={`text-sm font-semibold ${pctColor(stock.pct_change)}`}>
              {fmtPct(stock.pct_change)}
            </span>
            {stock.catalyst_type && (
              <span className="text-[10px] text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">
                {stock.catalyst_type}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <WatchlistButton code={stock.symbol} name={stock.name} />
          <span className="text-gray-600 text-xs">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* Collapsed preview */}
      {!expanded && (
        <div className="px-4 pb-3 space-y-1.5">
          {ruleHits.length > 0 && <RuleHitChips hits={ruleHits} />}
          {positives.slice(0, 2).map((r, i) => (
            <p key={i} className="text-xs text-gray-400 leading-relaxed">{r}</p>
          ))}
          {warns.length > 0 && (
            <p className="text-xs text-amber-500/80">{warns[0]}</p>
          )}
        </div>
      )}

      {/* Expanded */}
      {expanded && (
        <div className="border-t border-gray-800 px-4 py-3 space-y-3">
          {ruleHits.length > 0 && (
            <div className="bg-purple-900/15 rounded-lg p-3 border border-purple-800/30">
              <p className="text-xs text-purple-300 mb-1.5">🧠 命中你的交易规则</p>
              <div className="space-y-1.5">
                {ruleHits.map((h, i) => (
                  <div key={i} className="text-xs leading-relaxed flex gap-1.5 items-start">
                    <span className={`shrink-0 px-1 py-px rounded border text-[10px] ${ruleChipCls(h.direction)}`}>
                      {h.direction}
                    </span>
                    <span className="text-gray-300">
                      {h.note && <span className="text-gray-200">{h.note}　</span>}
                      <span className="text-gray-500">{h.rule}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <p className="text-xs text-gray-600 mb-1.5">分析依据</p>
            <div className="space-y-1.5">
              {positives.map((r, i) => (
                <p key={i} className="text-xs text-gray-300 leading-relaxed flex gap-1.5">
                  <span className="text-green-500 shrink-0 mt-px">✓</span>{r}
                </p>
              ))}
              {warns.map((r, i) => (
                <p key={i} className="text-xs text-amber-400/80 leading-relaxed">{r}</p>
              ))}
            </div>
          </div>

          {stock.strategy && (
            <div className="bg-gray-800/50 rounded-lg p-3 border border-gray-700/50">
              <p className="text-xs text-gray-500 mb-1">💡 入场策略</p>
              <p className="text-xs text-gray-300 leading-relaxed">{stock.strategy}</p>
            </div>
          )}

          <button
            onClick={e => { e.stopPropagation(); onSelect() }}
            className="w-full text-xs text-blue-400 hover:text-blue-300 text-center py-1"
          >查看复盘分析 →</button>
        </div>
      )}
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────
function EmptyRecommend({ icon, title, sub }: { icon: string; title: string; sub: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center space-y-2">
      <div className="text-4xl">{icon}</div>
      <p className="text-gray-400 font-medium">{title}</p>
      <p className="text-xs text-gray-600">{sub}</p>
    </div>
  )
}

// ── Loading spinner ───────────────────────────────────────────────────────────
function Spinner({ text = '加载中…' }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 text-gray-500 text-sm py-4">
      <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      {text}
    </div>
  )
}

// ── 推荐历史 ───────────────────────────────────────────────────────────────────
function HistoryCard({ rec, onSelect }: { rec: HistoryRecord; onSelect: () => void }) {
  const [open, setOpen] = useState(false)
  const warns     = rec.reasons.filter(r => r.startsWith('⚠️'))
  const positives = rec.reasons.filter(r => !r.startsWith('⚠️') && !r.startsWith('🧠'))
  const ruleHits  = rec.rule_hits ?? []
  const hm = (iso: string) => (iso || '').slice(11, 16)   // ISO → HH:MM

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden hover:border-gray-600 transition-all">
      <div className="flex items-center gap-3 p-3 cursor-pointer" onClick={() => setOpen(o => !o)}>
        <ScoreRing score={rec.peak_score} max={100} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-semibold text-white">{rec.name}</span>
            <span className="text-xs text-gray-600 font-mono">{rec.symbol}</span>
            <StrengthBadge s={rec.strength} />
            {rec.sector && (
              <span className="text-[10px] bg-purple-900/40 text-purple-300 border border-purple-800/40 px-1.5 py-0.5 rounded">{rec.sector}</span>
            )}
            {rec.mode === 'tomorrow' && (
              <span className="text-[10px] bg-indigo-900/40 text-indigo-300 border border-indigo-800/40 px-1.5 py-0.5 rounded">明日预判</span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500 flex-wrap">
            <span className="text-gray-400">峰值 {Math.round(rec.peak_score)} 分</span>
            <span className="text-gray-700">·</span>
            <span>{hm(rec.first_seen)}–{hm(rec.last_seen)} 入选 {rec.appear_count} 次</span>
            {rec.catalyst_type && (
              <span className="text-[10px] text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">{rec.catalyst_type}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <WatchlistButton code={rec.symbol} name={rec.name} />
          <span className="text-gray-600 text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </div>

      {!open && (
        <div className="px-3 pb-2.5 space-y-1.5">
          {ruleHits.length > 0 && <RuleHitChips hits={ruleHits} />}
          {positives.slice(0, 2).map((r, i) => (
            <p key={i} className="text-xs text-gray-400 leading-relaxed">{r}</p>
          ))}
        </div>
      )}

      {open && (
        <div className="border-t border-gray-800 px-3 py-3 space-y-3">
          {ruleHits.length > 0 && (
            <div className="bg-purple-900/15 rounded-lg p-3 border border-purple-800/30">
              <p className="text-xs text-purple-300 mb-1.5">🧠 命中你的交易规则</p>
              <div className="space-y-1.5">
                {ruleHits.map((h, i) => (
                  <div key={i} className="text-xs leading-relaxed flex gap-1.5 items-start">
                    <span className={`shrink-0 px-1 py-px rounded border text-[10px] ${ruleChipCls(h.direction)}`}>{h.direction}</span>
                    <span className="text-gray-300">
                      {h.note && <span className="text-gray-200">{h.note}　</span>}
                      <span className="text-gray-500">{h.rule}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <p className="text-xs text-gray-600 mb-1.5">当时的分析依据</p>
            <div className="space-y-1.5">
              {positives.map((r, i) => (
                <p key={i} className="text-xs text-gray-300 leading-relaxed flex gap-1.5">
                  <span className="text-green-500 shrink-0 mt-px">✓</span>{r}
                </p>
              ))}
              {warns.map((r, i) => (
                <p key={i} className="text-xs text-amber-400/80 leading-relaxed">{r}</p>
              ))}
            </div>
          </div>

          {rec.strategy && (
            <div className="bg-gray-800/50 rounded-lg p-3 border border-gray-700/50">
              <p className="text-xs text-gray-500 mb-1">💡 当时入场策略</p>
              <p className="text-xs text-gray-300 leading-relaxed">{rec.strategy}</p>
            </div>
          )}

          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-600">推荐当时 {rec.price.toFixed(2)}（{fmtPct(rec.pct_change)}）</span>
            <button
              onClick={e => { e.stopPropagation(); onSelect() }}
              className="text-blue-400 hover:text-blue-300"
            >查看复盘分析 →</button>
          </div>
        </div>
      )}
    </div>
  )
}

function HistoryPanel({ onSelectStock }: { onSelectStock?: (symbol: string, name: string) => void }) {
  const [q, setQ] = useState('')
  const { data, isLoading } = useQuery<HistoryResponse>({
    queryKey: ['recommend-history'],
    queryFn: async () => {
      const res = await fetch('/api/recommend/history?days=30')
      if (!res.ok) throw new Error('历史获取失败')
      return res.json()
    },
    staleTime: 60_000,
  })

  const all = data?.history ?? []
  const term = q.trim()
  const filtered = term ? all.filter(r => r.name.includes(term) || r.symbol.includes(term)) : all

  // 按日期分组（filtered 已是 date desc, peak desc）
  const groups: { date: string; items: HistoryRecord[] }[] = []
  for (const r of filtered) {
    let g = groups.find(x => x.date === r.trade_date)
    if (!g) { g = { date: r.trade_date, items: [] }; groups.push(g) }
    g.items.push(r)
  }

  return (
    <>
      <div className="space-y-1">
        <p className="text-sm font-medium text-emerald-300">📜 推荐历史</p>
        <p className="text-xs text-gray-500">每次推荐重算都会留痕，可回看当时的推荐逻辑（按股票名/代码搜索）</p>
        {data?.stats && (
          <p className="text-xs text-gray-600">共 {data.stats.total_records} 条记录 · {data.stats.total_days} 个交易日</p>
        )}
      </div>

      <input
        value={q}
        onChange={e => setQ(e.target.value)}
        placeholder="🔍 搜索股票名或代码，如 中远海控 / 601919"
        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-emerald-600 outline-none"
      />

      {isLoading && <Spinner text="加载历史…" />}
      {!isLoading && filtered.length === 0 && (
        <EmptyRecommend
          icon="📭"
          title={term ? `没有「${term}」的推荐记录` : '暂无推荐历史'}
          sub={term ? '换个关键词试试' : '系统会从现在起记录每天的推荐，之后这里就能回看了'}
        />
      )}

      <div className="space-y-5">
        {groups.map(g => (
          <div key={g.date} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-400">{g.date}</span>
              <span className="text-[10px] text-gray-600">{g.items.length} 只</span>
              <div className="flex-1 h-px bg-gray-800" />
            </div>
            <div className="space-y-2">
              {g.items.map(r => (
                <HistoryCard
                  key={`${r.trade_date}-${r.mode}-${r.symbol}`}
                  rec={r}
                  onSelect={() => onSelectStock?.(r.symbol, r.name)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
type Tab = 'watchlist' | 'today' | 'tomorrow' | 'history'

export default function WatchlistPage({ onSelectStock, view }: Props) {
  const items = useWatchlist()                         // 共享 store（带加入日期）
  const watchlist = items.map(i => i.code)             // 行情查询用的纯代码列表
  const [inputCode,   setInputCode]   = useState('')
  const [addError,    setAddError]    = useState('')
  const [notifyReady, setNotifyReady] = useState(false)
  const [activeTabState, setActiveTab] = useState<Tab>('watchlist')
  // 受控优先：App 顶层子tab 传入 view 时以其为准，否则用页内自带 tab
  const activeTab: Tab = view ?? activeTabState

  // ── 批量行情 ────────────────────────────────────────────────────────────────
  const { data: batchData, isLoading: batchLoading, refetch: refetchBatch } = useQuery<BatchResponse>({
    queryKey: ['watchlist-batch', watchlist.join(',')],
    queryFn: async () => {
      if (watchlist.length === 0) return { stocks: [], updated_at: '' }
      const res = await fetch(`/api/watchlist/batch?symbols=${watchlist.join(',')}`)
      if (!res.ok) throw new Error('行情获取失败')
      return res.json()
    },
    enabled: watchlist.length > 0,
    staleTime: 60_000,
    refetchInterval: 60_000,
  })

  // ── 今日推荐 ────────────────────────────────────────────────────────────────
  const { data: todayData, isLoading: todayLoading, refetch: refetchToday } = useQuery<RecommendResponse>({
    queryKey: ['recommend-today'],
    queryFn: async () => {
      const res = await fetch('/api/recommend/today')
      if (!res.ok) throw new Error('今日推荐获取失败')
      return res.json()
    },
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    enabled: activeTab === 'today',
  })

  // ── 明日推荐 ────────────────────────────────────────────────────────────────
  const { data: tomorrowData, isLoading: tomorrowLoading, refetch: refetchTomorrow } = useQuery<RecommendResponse>({
    queryKey: ['recommend-tomorrow'],
    queryFn: async () => {
      const res = await fetch('/api/recommend/tomorrow')
      if (!res.ok) throw new Error('明日推荐获取失败')
      return res.json()
    },
    staleTime: 60 * 60_000,  // 1 hour
    enabled: activeTab === 'tomorrow',
  })

  // ── 通知 ────────────────────────────────────────────────────────────────────
  useEffect(() => {
    requestNotify().then(ok => setNotifyReady(ok))
  }, [])

  useEffect(() => {
    if (!notifyReady || !todayData?.stocks.length) return
    const today = new Date().toLocaleDateString('zh-CN')
    if (localStorage.getItem(LS_NOTIFY_DATE) === today) return
    localStorage.setItem(LS_NOTIFY_DATE, today)
    const top3 = todayData.stocks.slice(0, 3).map(s => s.name).join('、')
    sendNotify(`📊 今日推荐`, `重点关注：${top3} 等 ${todayData.stocks.length} 只`)
  }, [notifyReady, todayData])

  // ── 自选管理（统一走 watchlistStore，跨页面同步）─────────────────────────────
  const handleAdd = useCallback((codeOverride?: string) => {
    const code = (codeOverride ?? inputCode).trim()
    if (!code) return
    if (!/^\d{6}$/.test(code)) { setAddError('请选择或输入 6 位股票代码'); return }
    if (watchlistStore.has(code)) { setAddError('已在自选列表中'); return }
    watchlistStore.add(code); setInputCode(''); setAddError('')
  }, [inputCode])

  const handleRemove = useCallback((code: string) => {
    watchlistStore.remove(code)
  }, [])

  const stocks: StockQuote[] = batchData?.stocks ?? []

  // 行情回来后把名称补进 store（分组标题/历史回看更友好）
  useEffect(() => {
    for (const s of stocks) {
      if (s.name && s.name !== '--') watchlistStore.fillName(s.symbol, s.name)
    }
  }, [stocks])

  // 按加入日期分组（新日期在前，'' 迁移数据排最后）
  const dateGroups = (() => {
    const map = new Map<string, typeof items>()
    for (const it of items) {
      const arr = map.get(it.date) ?? []
      arr.push(it); map.set(it.date, arr)
    }
    return Array.from(map.entries()).sort((a, b) => {
      if (a[0] === b[0]) return 0
      if (!a[0]) return 1        // '' 永远最后
      if (!b[0]) return -1
      return a[0] < b[0] ? 1 : -1   // 日期倒序
    })
  })()

  const TABS: { key: Tab; label: string; dot?: boolean }[] = [
    { key: 'watchlist', label: '📌 我的自选' },
    { key: 'today',     label: '🔥 今日推荐', dot: (todayData?.stocks.length ?? 0) > 0 },
    { key: 'tomorrow',  label: '🎯 明日预判', dot: (tomorrowData?.stocks.length ?? 0) > 0 },
    { key: 'history',   label: '📜 推荐历史' },
  ]

  return (
    <div className="min-h-screen bg-gray-950 px-4 py-6">
      <div className="max-w-5xl mx-auto space-y-5">

        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">自选 & 推荐</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              自选每分钟刷新 · 今日推荐5分钟更新 · 明日预判收盘后生成
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            {notifyReady ? (
              <span className="text-emerald-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />通知已开启
              </span>
            ) : (
              <button
                onClick={async () => setNotifyReady(await requestNotify())}
                className="text-gray-500 hover:text-blue-400 border border-gray-700 rounded-lg px-2.5 py-1"
              >🔔 开启推送</button>
            )}
          </div>
        </div>

        {/* Tabs（仅非受控时显示；受控时这四个 tab 已提到顶层导航栏） */}
        {view === undefined && (
          <div className="flex gap-2">
            {TABS.map(t => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={`relative text-sm px-4 py-2 rounded-lg font-medium transition-colors ${
                  activeTab === t.key
                    ? t.key === 'today'    ? 'bg-orange-600 text-white'
                    : t.key === 'tomorrow' ? 'bg-indigo-600 text-white'
                    : 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:text-white'
                }`}
              >
                {t.label}
                {t.dot && activeTab !== t.key && (
                  <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-green-400" />
                )}
              </button>
            ))}
          </div>
        )}

        {/* ── 自选股 ──────────────────────────────────────────────────────────── */}
        {activeTab === 'watchlist' && (
          <>
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
              <p className="text-xs text-gray-500 font-medium">添加自选股</p>
              <div className="flex gap-2 items-start">
                <div className="flex-1">
                  <StockSearch
                    value={inputCode}
                    onChange={(sym) => {
                      setInputCode(sym); setAddError('')
                      if (/^\d{6}$/.test(sym)) handleAdd(sym)
                    }}
                    placeholder="股票代码 / 名称 / 拼音缩写"
                  />
                </div>
                <button
                  onClick={() => handleAdd()}
                  disabled={!inputCode.trim()}
                  className="text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-lg px-4 py-2 font-medium transition-colors"
                >+ 添加</button>
                {watchlist.length > 0 && (
                  <button
                    onClick={() => refetchBatch()}
                    className="text-xs text-gray-400 hover:text-white border border-gray-700 rounded-lg px-3 py-2"
                  >🔄</button>
                )}
              </div>
              {addError && <p className="text-red-400 text-xs">{addError}</p>}
              {batchData?.updated_at && <p className="text-xs text-gray-700">行情更新 {batchData.updated_at}</p>}
            </div>

            {watchlist.length === 0 ? (
              <EmptyRecommend icon="📌" title="还没有自选股"
                sub="输入代码添加，或在规则库/推荐/龙虎榜等任何看到股票的地方点 ☆ 加入。按加入日期分组，方便回看每天选的股表现" />
            ) : (
              <>
                {batchLoading && <Spinner text="加载行情…" />}
                {/* 按加入日期分组：今天加的归「6.17 自选」，以此类推 */}
                <div className="space-y-5">
                  {dateGroups.map(([date, groupItems]) => (
                    <div key={date || 'older'} className="space-y-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-amber-300">📅 {dateLabel(date)}</span>
                        <span className="text-[10px] text-gray-600">{groupItems.length} 只</span>
                        <div className="flex-1 h-px bg-gray-800" />
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                        {groupItems.map(({ code }) => {
                          const stock = stocks.find(s => s.symbol === code)
                          if (!stock) return (
                            <div key={code} className="bg-gray-900 border border-gray-800 rounded-xl p-4 animate-pulse">
                              <div className="h-4 bg-gray-800 rounded w-24 mb-2" />
                              <div className="h-6 bg-gray-800 rounded w-16" />
                            </div>
                          )
                          return (
                            <QuoteCard key={code} stock={stock}
                              onSelect={() => onSelectStock?.(stock.symbol, stock.name)}
                              onRemove={() => handleRemove(code)} />
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}

        {/* ── 今日推荐 ─────────────────────────────────────────────────────────── */}
        {activeTab === 'today' && (
          <>
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <p className="text-sm font-medium text-orange-300">🔥 盘中实时可入推荐</p>
                <p className="text-xs text-gray-500">
                  综合热点主题 · 资金信号 · 技术入场窗口，过滤追高风险
                </p>
                {todayData?.updated_at && (
                  <p className="text-xs text-gray-600">最近更新 {todayData.updated_at}
                    {todayData.cached && <span className="ml-1 text-gray-700">(缓存)</span>}
                    {todayData.news_latest && (
                      <span className="ml-2 text-emerald-600/90">· 消息截止 {todayData.news_latest}</span>
                    )}
                  </p>
                )}
              </div>
              <button
                onClick={() => refetchToday()}
                className="text-xs text-gray-400 hover:text-white border border-gray-700 rounded-lg px-3 py-1.5 shrink-0"
              >🔄 刷新</button>
            </div>

            {/* How it works */}
            <div className="bg-gray-900/50 border border-gray-800 rounded-lg px-4 py-2.5 text-xs text-gray-500 flex flex-wrap gap-x-4 gap-y-1">
              <span>驱动逻辑：</span>
              <span className="text-orange-400">📰 新闻消息面（DeepSeek提取催化剂）</span>
              <span className="text-yellow-400">🐉 龙虎榜资金</span>
              <span className="text-blue-400">📡 北向资金</span>
              <span className="text-purple-400">🔥 板块热度</span>
              <span className="text-gray-600 ml-auto">过滤涨停/大跌股</span>
            </div>

            {todayLoading && <Spinner text="正在读取最新快讯并分析（约10-15秒）…" />}

            {!todayLoading && !todayData?.stocks.length && (
              <EmptyRecommend icon="📰" title="暂无今日推荐"
                sub="暂无明确催化剂股票，或当前处于非交易时段。可手动刷新" />
            )}

            {todayData && todayData.stocks.length > 0 && (
              <div className="space-y-3">
                {/* Hot themes */}
                {todayData.hot_themes && todayData.hot_themes.length > 0 && (
                  <div className="bg-gray-800/60 border border-gray-700/60 rounded-lg px-4 py-2.5">
                    <span className="text-xs text-gray-500 mr-2">今日热门主题：</span>
                    {todayData.hot_themes.map((t, i) => (
                      <span key={i} className="inline-block text-xs bg-orange-900/40 text-orange-300 border border-orange-800/40 px-2 py-0.5 rounded-full mr-1.5">
                        {t}
                      </span>
                    ))}
                    {todayData.market_sentiment && (
                      <span className={`ml-2 text-xs px-2 py-0.5 rounded-full border ${
                        todayData.market_sentiment === '偏多'
                          ? 'bg-red-900/30 text-red-300 border-red-800/40'
                          : todayData.market_sentiment === '偏空'
                          ? 'bg-blue-900/30 text-blue-300 border-blue-800/40'
                          : 'bg-gray-800 text-gray-400 border-gray-700'
                      }`}>市场：{todayData.market_sentiment}</span>
                    )}
                  </div>
                )}

                <div className="bg-orange-900/20 border border-orange-800/40 rounded-lg px-4 py-2.5 text-sm text-orange-300">
                  今日重点关注：
                  {todayData.stocks.slice(0, 3).map(s => (
                    <button key={s.symbol}
                      onClick={() => onSelectStock?.(s.symbol, s.name)}
                      className="ml-2 font-semibold hover:text-white underline underline-offset-2"
                    >{s.name}({s.score.toFixed(0)}分)</button>
                  ))}
                  {todayData.stocks.length > 3 && <span className="text-orange-600 ml-1">等 {todayData.stocks.length} 只</span>}
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  {todayData.stocks.map(s => (
                    <RecommendCard key={s.symbol} stock={s}
                      onSelect={() => onSelectStock?.(s.symbol, s.name)} />
                  ))}
                </div>
                <p className="text-xs text-gray-700 text-center pt-1">
                  ⚠️ 以上内容仅供参考，不构成投资建议
                </p>
              </div>
            )}
          </>
        )}

        {/* ── 明日预判 ─────────────────────────────────────────────────────────── */}
        {activeTab === 'tomorrow' && (
          <>
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <p className="text-sm font-medium text-indigo-300">🎯 明日布局预判</p>
                <p className="text-xs text-gray-500">
                  基于今日收盘 · 结合主题延续性 · 技术形态 · 资金流向
                </p>
                {tomorrowData && (
                  <p className="text-xs text-gray-600">
                    {tomorrowData.date} 收盘后生成
                    {tomorrowData.cached && <span className="ml-1 text-gray-700">(缓存)</span>}
                    {tomorrowData.news_latest && (
                      <span className="ml-2 text-emerald-600/90">· 消息截止 {tomorrowData.news_latest}</span>
                    )}
                  </p>
                )}
              </div>
              <button
                onClick={() => refetchTomorrow()}
                className="text-xs text-gray-400 hover:text-white border border-gray-700 rounded-lg px-3 py-1.5 shrink-0"
              >🔄 刷新</button>
            </div>

            {/* How it works */}
            <div className="bg-gray-900/50 border border-gray-800 rounded-lg px-4 py-2.5 text-xs text-gray-500 flex flex-wrap gap-x-4 gap-y-1">
              <span>驱动逻辑：</span>
              <span className="text-indigo-400">📰 今日消息面（盘后公告/盘中未充分反映）</span>
              <span className="text-yellow-400">🐉 龙虎榜布局</span>
              <span className="text-blue-400">📡 北向动向</span>
              <span className="text-gray-600 ml-auto">收盘后刷新效果最佳</span>
            </div>

            {tomorrowLoading && <Spinner text="正在分析明日预判（约10-15秒）…" />}

            {!tomorrowLoading && !tomorrowData?.stocks.length && (
              <EmptyRecommend icon="🎯" title="暂无明日预判"
                sub="收盘后（15:30后）刷新效果最佳，系统会分析今日收盘情况" />
            )}

            {tomorrowData && tomorrowData.stocks.length > 0 && (
              <div className="space-y-3">
                {tomorrowData.hot_themes && tomorrowData.hot_themes.length > 0 && (
                  <div className="bg-gray-800/60 border border-gray-700/60 rounded-lg px-4 py-2.5">
                    <span className="text-xs text-gray-500 mr-2">今日热门主题：</span>
                    {tomorrowData.hot_themes.map((t, i) => (
                      <span key={i} className="inline-block text-xs bg-indigo-900/40 text-indigo-300 border border-indigo-800/40 px-2 py-0.5 rounded-full mr-1.5">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                <div className="bg-indigo-900/20 border border-indigo-800/40 rounded-lg px-4 py-2.5 text-sm text-indigo-300">
                  明日重点布局：
                  {tomorrowData.stocks.slice(0, 3).map(s => (
                    <button key={s.symbol}
                      onClick={() => onSelectStock?.(s.symbol, s.name)}
                      className="ml-2 font-semibold hover:text-white underline underline-offset-2"
                    >{s.name}({s.score.toFixed(0)}分)</button>
                  ))}
                  {tomorrowData.stocks.length > 3 && <span className="text-indigo-600 ml-1">等 {tomorrowData.stocks.length} 只</span>}
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  {tomorrowData.stocks.map(s => (
                    <RecommendCard key={s.symbol} stock={s}
                      onSelect={() => onSelectStock?.(s.symbol, s.name)} />
                  ))}
                </div>
                <p className="text-xs text-gray-700 text-center pt-1">
                  ⚠️ 以上内容仅供参考，不构成投资建议
                </p>
              </div>
            )}
          </>
        )}

        {/* ── 推荐历史 ─────────────────────────────────────────────────────────── */}
        {activeTab === 'history' && <HistoryPanel onSelectStock={onSelectStock} />}

      </div>
    </div>
  )
}
