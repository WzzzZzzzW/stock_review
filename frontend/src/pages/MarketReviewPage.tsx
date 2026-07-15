import { useState, useEffect, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// ── 类型 ────────────────────────────────────────────────────────────────────
interface RankItem {
  symbol: string; name: string; price: number | null
  change_pct: number | null; turnover: number | null; amount_yi: number
}
interface LadderRow { height: number; count: number; names: string[] }
interface Leader { symbol: string; name: string; zt_today: number; industry: string; seal_amount: number }
interface IndexItem { key: string; name: string; price: number; change: number; pct: number }
interface SectorItem { name: string; pct: number; leader: string; type: string }
interface CapTier { tier: string; count: number; avg_pct: number; up: number; down: number }
interface DistBin { label: string; count: number; side: 'up' | 'down' }
interface DtStock { symbol: string; name: string; pct: number; price: number; industry: string; dt_days: number }

interface Review {
  trade_date: string; generated_at: string; is_today: boolean
  breadth: { up: number; down: number; flat: number; total: number; up_ratio: number; up_over5: number; down_over5: number }
  distribution: DistBin[]
  limit_stats: {
    zt_count: number; dt_count: number; broken_count: number; broken_ratio: number
    max_continuity: number; ladder: LadderRow[]; leaders: Leader[]
    zt_by_industry: { industry: string; count: number }[]; dt_stocks: DtStock[]
  }
  amount: { total: number; total_yi: number }
  rankings: { gainers: RankItem[]; losers: RankItem[]; amount: RankItem[]; turnover: RankItem[] }
  cap_perf: CapTier[]
  indices: IndexItem[]
  sectors: { top_up: SectorItem[]; top_down: SectorItem[] }
  sentiment: { score: number; label: string; emoji: string; color: string; desc: string; index_avg: number }
  summary: string
  ai_review?: string
  news?: NewsItem[]
}

interface NewsItem { title: string; summary: string; source: string; published: string; url: string }

interface DateEntry { date: string; up_count: number; down_count: number; zt_count: number; sentiment_score: number; generated_at: string }
interface GeneratingStatus { running: boolean; started_at: string; progress: string }

const API = ''

// ── 工具 ────────────────────────────────────────────────────────────────────
// A股惯例：红涨 绿跌
const pctColor = (v: number | null | undefined) =>
  v == null ? 'text-gray-400' : v > 0 ? 'text-red-400' : v < 0 ? 'text-green-400' : 'text-gray-300'
const fmtPct = (v: number | null | undefined) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

// ── 日历日期选择器（与涨停板一致）────────────────────────────────────────────
interface CalendarProps {
  value: string; today: string; datesWithData: Set<string>
  onSelect: (date: string) => void; onGenerate: (date: string) => void; generating: boolean
}
function DateCalendar({ value, today, datesWithData, onSelect, onGenerate, generating }: CalendarProps) {
  const [viewMonth, setViewMonth] = useState(() => {
    const d = new Date(value || today)
    return new Date(d.getFullYear(), d.getMonth(), 1)
  })
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const year = viewMonth.getFullYear()
  const month = viewMonth.getMonth()
  const startWeekday = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()

  const cells: { date: string | null; day: number | null }[] = []
  for (let i = 0; i < startWeekday; i++) cells.push({ date: null, day: null })
  for (let d = 1; d <= daysInMonth; d++) {
    const dStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    cells.push({ date: dStr, day: d })
  }
  while (cells.length % 7 !== 0) cells.push({ date: null, day: null })

  const isWeekend = (dStr: string) => {
    const dow = new Date(dStr).getDay()
    return dow === 0 || dow === 6
  }
  const handleCellClick = (dStr: string) => {
    if (isWeekend(dStr) || dStr > today) return
    if (datesWithData.has(dStr)) { onSelect(dStr); setOpen(false) }
    else { onGenerate(dStr); setOpen(false) }
  }

  return (
    <div ref={wrapperRef} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 flex items-center gap-2 min-w-[160px]"
      >
        <span>📅</span>
        <span className="font-mono">{value || today}</span>
        {datesWithData.has(value) && <span className="text-[10px] text-green-400">●</span>}
        <span className="ml-auto text-gray-500">▾</span>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl p-3 z-50 w-[280px]">
          <div className="flex items-center justify-between mb-2">
            <button onClick={() => setViewMonth(new Date(year, month - 1, 1))} className="text-gray-400 hover:text-white p-1 hover:bg-gray-800 rounded">‹</button>
            <span className="text-sm font-semibold text-white">{`${year}年${month + 1}月`}</span>
            <button onClick={() => setViewMonth(new Date(year, month + 1, 1))} className="text-gray-400 hover:text-white p-1 hover:bg-gray-800 rounded">›</button>
          </div>
          <div className="grid grid-cols-7 gap-1 mb-1">
            {['日', '一', '二', '三', '四', '五', '六'].map((w, i) => (
              <div key={w} className={`text-[10px] text-center font-medium ${i === 0 || i === 6 ? 'text-gray-600' : 'text-gray-400'}`}>{w}</div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {cells.map((cell, i) => {
              if (!cell.date) return <div key={i} />
              const dStr = cell.date
              const isWE = isWeekend(dStr)
              const isFuture = dStr > today
              const isSelected = dStr === value
              const isToday = dStr === today
              const hasData = datesWithData.has(dStr)
              const baseCls = 'h-8 text-xs rounded flex items-center justify-center font-mono transition-colors relative'
              if (isFuture || isWE) return <div key={i} className={`${baseCls} text-gray-700`}>{cell.day}</div>
              if (hasData) {
                return (
                  <button key={i} onClick={() => handleCellClick(dStr)}
                    className={`${baseCls} ${isSelected ? 'bg-blue-600 text-white' : 'bg-green-900/50 text-green-300 hover:bg-green-800/70'} ${isToday ? 'ring-1 ring-amber-400' : ''}`}
                    title={`${dStr} 已有数据，点击查看`}>
                    {cell.day}
                    <span className="absolute bottom-0.5 right-1 w-1 h-1 rounded-full bg-green-400" />
                  </button>
                )
              }
              return (
                <button key={i} onClick={() => handleCellClick(dStr)} disabled={generating}
                  className={`${baseCls} ${isSelected ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-500 hover:bg-blue-900/40 hover:text-blue-300'} ${isToday ? 'ring-1 ring-amber-400' : ''} ${generating ? 'opacity-40 cursor-wait' : ''}`}
                  title={isToday ? '今日待生成，点击触发' : `${dStr} 暂无数据，点击触发后台生成`}>
                  {cell.day}
                </button>
              )
            })}
          </div>
          <div className="flex items-center gap-3 mt-3 pt-2 border-t border-gray-800 text-[10px] text-gray-500">
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-green-900/50 border border-green-700" />已有</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-gray-800 border border-gray-700" />未生成</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-blue-600" />当前</span>
          </div>
          <p className="text-[10px] text-gray-600 mt-1.5 leading-relaxed">💡 点已有数据查看 · 点未生成日期自动后台补齐（约10-20秒）</p>
        </div>
      )}
    </div>
  )
}

// ── 子组件 ──────────────────────────────────────────────────────────────────

function SentimentGauge({ s }: { s: Review['sentiment'] }) {
  const colorMap: Record<string, { ring: string; text: string; bg: string }> = {
    red: { ring: 'border-red-500', text: 'text-red-400', bg: 'from-red-900/40' },
    orange: { ring: 'border-orange-500', text: 'text-orange-400', bg: 'from-orange-900/40' },
    gray: { ring: 'border-gray-500', text: 'text-gray-300', bg: 'from-gray-800/40' },
    cyan: { ring: 'border-cyan-500', text: 'text-cyan-400', bg: 'from-cyan-900/40' },
    blue: { ring: 'border-blue-500', text: 'text-blue-400', bg: 'from-blue-900/40' },
  }
  const c = colorMap[s.color] || colorMap.gray
  return (
    <div className={`flex items-center gap-5 px-5 py-4 rounded-xl border border-gray-800 bg-gradient-to-r ${c.bg} to-gray-900`}>
      <div className={`flex flex-col items-center justify-center w-24 h-24 rounded-full border-4 ${c.ring} shrink-0`}>
        <span className="text-3xl leading-none">{s.emoji}</span>
        <span className={`text-2xl font-bold ${c.text} leading-tight mt-1`}>{s.score}</span>
        <span className="text-[10px] text-gray-500">情绪温度</span>
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-xl font-bold ${c.text}`}>{s.label}</span>
          <span className="text-xs text-gray-500">指数均值 {fmtPct(s.index_avg)}</span>
        </div>
        <p className="text-sm text-gray-400 mt-1">{s.desc}</p>
      </div>
    </div>
  )
}

function StatBox({ label, value, sub, color = 'text-white' }: { label: string; value: React.ReactNode; sub?: string; color?: string }) {
  return (
    <div className="px-3 py-2 rounded-lg bg-gray-900 border border-gray-800 min-w-[92px]">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className={`text-lg font-bold ${color} leading-tight`}>{value}</div>
      {sub && <div className="text-[10px] text-gray-600 mt-0.5">{sub}</div>}
    </div>
  )
}

// 涨跌家数比例条
function BreadthBar({ b }: { b: Review['breadth'] }) {
  const total = b.up + b.flat + b.down || 1
  const upW = (b.up / total) * 100
  const flatW = (b.flat / total) * 100
  const downW = (b.down / total) * 100
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1.5">
        <span className="text-red-400 font-medium">上涨 {b.up}</span>
        <span className="text-gray-500">平 {b.flat}</span>
        <span className="text-green-400 font-medium">下跌 {b.down}</span>
      </div>
      <div className="flex h-4 rounded overflow-hidden bg-gray-800">
        <div className="bg-red-600/80 h-full flex items-center justify-center" style={{ width: `${upW}%` }}>
          {upW > 12 && <span className="text-[10px] text-white">{Math.round(upW)}%</span>}
        </div>
        <div className="bg-gray-600 h-full" style={{ width: `${flatW}%` }} />
        <div className="bg-green-600/80 h-full flex items-center justify-center" style={{ width: `${downW}%` }}>
          {downW > 12 && <span className="text-[10px] text-white">{Math.round(downW)}%</span>}
        </div>
      </div>
      <div className="flex gap-4 mt-2 text-[11px] text-gray-500">
        <span>涨超5% <span className="text-red-400">{b.up_over5}</span></span>
        <span>跌超5% <span className="text-green-400">{b.down_over5}</span></span>
        <span>赚钱效应 <span className="text-gray-300">{b.up_ratio}%</span></span>
      </div>
    </div>
  )
}

// 涨跌分布直方图
function DistributionChart({ dist }: { dist: DistBin[] }) {
  const max = Math.max(...dist.map(d => d.count), 1)
  return (
    <div className="space-y-1">
      {dist.slice().reverse().map(d => (
        <div key={d.label} className="flex items-center gap-2">
          <span className="w-16 text-[11px] text-gray-500 text-right shrink-0">{d.label}</span>
          <div className="flex-1 h-4 bg-gray-800/60 rounded overflow-hidden">
            <div
              className={`h-full rounded ${d.side === 'up' ? 'bg-red-600/70' : 'bg-green-600/70'}`}
              style={{ width: `${(d.count / max) * 100}%` }}
            />
          </div>
          <span className={`w-10 text-[11px] text-right shrink-0 ${d.side === 'up' ? 'text-red-400' : 'text-green-400'}`}>{d.count}</span>
        </div>
      ))}
    </div>
  )
}

function BoardBadge({ n }: { n: number }) {
  const base = 'inline-flex items-center justify-center min-w-[30px] h-5 px-1.5 rounded text-[11px] font-bold whitespace-nowrap leading-none'
  if (n >= 7) return <span className={`${base} bg-gradient-to-r from-red-700 to-pink-600 text-white border border-red-400`}>{n}板</span>
  if (n >= 5) return <span className={`${base} bg-red-700 text-white border border-red-500`}>{n}板</span>
  if (n === 4) return <span className={`${base} bg-red-600 text-white`}>4板</span>
  if (n === 3) return <span className={`${base} bg-orange-600 text-white`}>3板</span>
  if (n === 2) return <span className={`${base} bg-orange-500 text-white`}>2板</span>
  return <span className={`${base} bg-gray-700 text-gray-300`}>首板</span>
}

// 连板梯队
function LadderView({ ladder }: { ladder: LadderRow[] }) {
  return (
    <div className="space-y-2">
      {ladder.map(row => (
        <div key={row.height} className="flex items-start gap-3">
          <div className="shrink-0 pt-0.5"><BoardBadge n={row.height} /></div>
          <span className="text-xs text-gray-500 shrink-0 pt-1">×{row.count}</span>
          <div className="flex flex-wrap gap-1.5">
            {row.names.map(n => (
              <span key={n} className={`text-xs px-2 py-0.5 rounded border ${row.height >= 3 ? 'bg-red-900/30 text-red-300 border-red-800/50' : 'bg-gray-800 text-gray-300 border-gray-700'}`}>{n}</span>
            ))}
            {row.count > row.names.length && <span className="text-xs text-gray-600 px-1 pt-0.5">+{row.count - row.names.length}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}

// 市值分层表现
function CapPerfView({ tiers }: { tiers: CapTier[] }) {
  const maxAbs = Math.max(...tiers.map(t => Math.abs(t.avg_pct)), 0.5)
  return (
    <div className="space-y-2">
      {tiers.map(t => {
        const w = (Math.abs(t.avg_pct) / maxAbs) * 50  // 半轴最大 50%
        const up = t.avg_pct > 0
        return (
          <div key={t.tier} className="flex items-center gap-2 text-xs">
            <span className="w-32 text-gray-400 shrink-0 truncate" title={t.tier}>{t.tier}</span>
            <div className="flex-1 flex items-center">
              <div className="w-1/2 flex justify-end">
                {!up && <div className="h-3.5 bg-green-600/70 rounded-l" style={{ width: `${w}%` }} />}
              </div>
              <div className="w-px h-4 bg-gray-700" />
              <div className="w-1/2">
                {up && <div className="h-3.5 bg-red-600/70 rounded-r" style={{ width: `${w}%` }} />}
              </div>
            </div>
            <span className={`w-14 text-right shrink-0 ${pctColor(t.avg_pct)}`}>{fmtPct(t.avg_pct)}</span>
            <span className="w-24 text-right shrink-0 text-gray-600">
              <span className="text-red-400">{t.up}</span>/<span className="text-green-400">{t.down}</span>
              <span className="text-gray-700"> ({t.count})</span>
            </span>
          </div>
        )
      })}
    </div>
  )
}

// 榜单表
function RankTable({ items, kind }: { items: RankItem[]; kind: 'pct' | 'amount' | 'turnover' }) {
  if (!items?.length) return <div className="text-xs text-gray-600 py-4 text-center">暂无数据</div>
  return (
    <table className="w-full text-xs">
      <tbody>
        {items.map((s, i) => (
          <tr key={s.symbol} className="border-b border-gray-800/40 hover:bg-gray-800/30">
            <td className="py-1.5 pr-1 text-gray-600 w-5 text-right">{i + 1}</td>
            <td className="py-1.5 pr-2">
              <span className="text-gray-200">{s.name}</span>
              <span className="text-gray-600 font-mono text-[10px] ml-1">{s.symbol}</span>
            </td>
            <td className="py-1.5 px-1 text-right text-gray-400 font-mono">{s.price?.toFixed(2) ?? '--'}</td>
            <td className={`py-1.5 pl-2 text-right font-mono ${kind === 'pct' ? pctColor(s.change_pct) : 'text-gray-300'}`}>
              {kind === 'amount' ? `${s.amount_yi.toFixed(1)}亿`
                : kind === 'turnover' ? `${s.turnover?.toFixed(1) ?? '--'}%`
                : fmtPct(s.change_pct)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SectorList({ items, up }: { items: SectorItem[]; up: boolean }) {
  if (!items?.length) return <div className="text-xs text-gray-600 py-2">暂无数据</div>
  return (
    <div className="space-y-1">
      {items.map(s => (
        <div key={s.name + s.type} className="flex items-center gap-2 text-xs">
          <span className="text-gray-200 truncate flex-1">{s.name}</span>
          <span className="text-[10px] px-1 rounded bg-gray-800 text-gray-500">{s.type}</span>
          {s.leader && <span className="text-[10px] text-gray-600 truncate max-w-[70px]">{s.leader}</span>}
          <span className={`w-14 text-right font-mono ${up ? 'text-red-400' : 'text-green-400'}`}>{fmtPct(s.pct)}</span>
        </div>
      ))}
    </div>
  )
}

function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-200">{title}</h3>
        {right}
      </div>
      {children}
    </div>
  )
}

// ── 主页面 ──────────────────────────────────────────────────────────────────
export default function MarketReviewPage() {
  const [review, setReview] = useState<Review | null>(null)
  const [dates, setDates] = useState<DateEntry[]>([])
  const [selectedDate, setSelectedDate] = useState('')
  const [status, setStatus] = useState<GeneratingStatus>({ running: false, started_at: '', progress: '' })
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [rankTab, setRankTab] = useState<'gainers' | 'losers' | 'amount' | 'turnover'>('gainers')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const today = new Date().toISOString().slice(0, 10)

  const loadDates = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/market-review/dates`)
      const j = await res.json()
      setDates(j.dates || [])
    } catch {}
  }, [])

  const loadReview = useCallback(async (d?: string) => {
    setLoading(true)
    try {
      const url = d ? `${API}/api/market-review/daily?date=${d}` : `${API}/api/market-review/daily`
      const res = await fetch(url)
      const j = await res.json()
      if (j.data) {
        setReview(j.data)
        setSelectedDate(j.data.trade_date)
        setMessage('')
      } else {
        setReview(null)
        setMessage(j.message || '暂无数据')
      }
      if (j.generating_status) setStatus(j.generating_status)
    } catch {
      setMessage('请求失败，请检查后端服务')
    } finally {
      setLoading(false)
    }
  }, [])

  const pollStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/market-review/status`)
      const j = await res.json()
      setStatus(j)
      if (!j.running) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        await loadDates()
        await loadReview(selectedDate || undefined)
      }
    } catch {}
  }, [loadDates, loadReview, selectedDate])

  const startGenerate = useCallback(async (d?: string) => {
    const target = d || today
    try {
      const res = await fetch(`${API}/api/market-review/generate?date=${target}`, { method: 'POST' })
      const j = await res.json()
      setMessage(j.message)
      if (j.ok) {
        setStatus({ running: true, started_at: new Date().toISOString(), progress: '启动中...' })
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(pollStatus, 3000)
      }
    } catch {
      setMessage('触发失败')
    }
  }, [today, pollStatus])

  useEffect(() => { loadDates(); loadReview() }, [loadDates, loadReview])
  useEffect(() => {
    if (status.running && !pollRef.current) pollRef.current = setInterval(pollStatus, 3000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [status.running, pollStatus])

  const handleDateChange = (d: string) => { setSelectedDate(d); loadReview(d) }
  const isToday = selectedDate === today || (!selectedDate && !review)
  const todayHasData = dates.some(d => d.date === today)
  const ls = review?.limit_stats

  return (
    <div className="min-h-screen bg-gray-950 text-gray-200 p-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div>
          <h1 className="text-xl font-bold text-white">今日市场复盘</h1>
          <p className="text-xs text-gray-500 mt-0.5">多维度 · 每日自动生成 · 历史永久保存</p>
        </div>
        <div className="flex items-center gap-2 ml-auto flex-wrap">
          <DateCalendar
            value={selectedDate || today}
            today={today}
            datesWithData={new Set(dates.map(d => d.date))}
            onSelect={handleDateChange}
            onGenerate={(d) => startGenerate(d)}
            generating={status.running}
          />
          <button
            onClick={() => startGenerate(selectedDate || today)}
            disabled={status.running}
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${status.running ? 'bg-gray-700 text-gray-500 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-500 text-white'}`}
            title={isToday && !todayHasData ? '生成今日数据' : '重新生成当前日期'}
          >
            {status.running ? '生成中...' : (isToday && !todayHasData ? '🚀 生成今日' : '🔄 重新生成')}
          </button>
        </div>
      </div>

      {/* Status bar */}
      {(status.running || status.progress) && (
        <div className={`mb-4 px-4 py-3 rounded-lg border text-sm ${status.running ? 'bg-blue-950 border-blue-800 text-blue-300' : status.progress.startsWith('失败') ? 'bg-red-950 border-red-800 text-red-300' : 'bg-green-950 border-green-800 text-green-300'}`}>
          <div className="flex items-center gap-2">
            {status.running && (
              <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            <span>{status.progress}</span>
          </div>
        </div>
      )}

      {message && !status.running && !review && (
        <div className="mb-4 px-4 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-400">{message}</div>
      )}

      {/* No data */}
      {!loading && !review && !status.running && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="text-5xl mb-4">📊</div>
          <p className="text-gray-400 text-lg mb-2">暂无复盘数据</p>
          <p className="text-gray-600 text-sm mb-6">
            {isToday ? '今日复盘尚未生成，每日 15:50 自动触发，或手动点击生成' : '该日期无数据'}
          </p>
          <button onClick={() => startGenerate(selectedDate || today)} className="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors">立即生成</button>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-20 text-gray-500">
          <svg className="animate-spin h-6 w-6 mr-2" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          加载中...
        </div>
      )}

      {/* Review content */}
      {review && !loading && ls && (
        <div className="space-y-4">
          {/* 一句话总结 */}
          <p className="text-sm text-gray-400 leading-relaxed px-1">{review.summary}</p>

          {/* AI 复盘点评 */}
          {review.ai_review && (
            <div className="bg-gradient-to-br from-indigo-950/40 to-gray-900 border border-indigo-800/40 rounded-xl p-4 sm:p-5">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-base">🤖</span>
                <span className="text-sm font-semibold text-indigo-300">AI 智能复盘点评</span>
                <span className="text-[10px] text-gray-600 ml-auto">由大模型综合数据与要闻生成 · 仅供参考</span>
              </div>
              <div className="prose prose-invert prose-sm max-w-none text-gray-200 leading-relaxed
                              prose-headings:text-indigo-300 prose-headings:text-sm prose-headings:font-bold
                              prose-headings:mt-3 prose-headings:mb-1.5 prose-p:my-1.5 prose-li:my-0.5
                              prose-strong:text-white">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{review.ai_review}</ReactMarkdown>
              </div>
            </div>
          )}

          {/* 情绪温度计 + 核心指标 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <SentimentGauge s={review.sentiment} />
            <div className="grid grid-cols-3 sm:grid-cols-3 gap-2 content-center">
              <StatBox label="涨停" value={ls.zt_count} color="text-red-400" sub={`最高 ${ls.max_continuity} 连板`} />
              <StatBox label="跌停" value={ls.dt_count} color="text-green-400" sub={`炸板率 ${ls.broken_ratio}%`} />
              <StatBox label="两市成交" value={`${(review.amount.total_yi / 1).toFixed(0)}`} color="text-amber-400" sub="亿元" />
              <StatBox label="上涨" value={review.breadth.up} color="text-red-400" />
              <StatBox label="下跌" value={review.breadth.down} color="text-green-400" />
              <StatBox label="炸板" value={ls.broken_count} color="text-orange-400" sub="只" />
            </div>
          </div>

          {/* 大盘指数 */}
          {review.indices.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {review.indices.map(idx => (
                <div key={idx.key} className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2">
                  <div className="text-[11px] text-gray-500">{idx.name}</div>
                  <div className={`text-lg font-bold font-mono ${pctColor(idx.pct)}`}>{idx.price?.toFixed(2)}</div>
                  <div className={`text-xs font-mono ${pctColor(idx.pct)}`}>{fmtPct(idx.pct)}</div>
                </div>
              ))}
            </div>
          )}

          {/* 涨跌家数 + 涨跌分布 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Section title="涨跌家数"><BreadthBar b={review.breadth} /></Section>
            <Section title="涨跌幅分布"><DistributionChart dist={review.distribution} /></Section>
          </div>

          {/* 连板梯队 + 涨停行业 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Section title="连板梯队" right={<span className="text-xs text-gray-500">涨停 {ls.zt_count} · 最高 {ls.max_continuity} 板</span>}>
              {ls.ladder.length ? <LadderView ladder={ls.ladder} /> : <div className="text-xs text-gray-600 py-4 text-center">当日无涨停</div>}
            </Section>
            <Section title="涨停行业分布">
              {ls.zt_by_industry.length ? (
                <div className="flex flex-wrap gap-2">
                  {ls.zt_by_industry.map(it => (
                    <span key={it.industry} className="text-xs px-2.5 py-1 rounded-full bg-red-900/30 text-red-300 border border-red-800/50">
                      {it.industry} <span className="text-red-400 font-bold">{it.count}</span>
                    </span>
                  ))}
                </div>
              ) : <div className="text-xs text-gray-600 py-4 text-center">无数据</div>}
              {/* 跌停 */}
              {ls.dt_stocks.length > 0 && (
                <div className="mt-4 pt-3 border-t border-gray-800">
                  <div className="text-xs text-gray-500 mb-2">跌停 {ls.dt_count} 只</div>
                  <div className="flex flex-wrap gap-1.5">
                    {ls.dt_stocks.map(s => (
                      <span key={s.symbol} className="text-xs px-2 py-0.5 rounded bg-green-900/30 text-green-300 border border-green-800/50">
                        {s.name}{s.dt_days > 1 && <span className="text-green-500 ml-0.5">{s.dt_days}连跌</span>}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </Section>
          </div>

          {/* 市值分层表现 */}
          <Section title="市值分层表现" right={<span className="text-[11px] text-gray-600">平均涨跌幅 · 红涨/绿跌（家数）</span>}>
            <CapPerfView tiers={review.cap_perf} />
          </Section>

          {/* 板块热力 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Section title="🔥 领涨板块"><SectorList items={review.sectors.top_up} up /></Section>
            <Section title="❄️ 领跌板块"><SectorList items={review.sectors.top_down} up={false} /></Section>
          </div>

          {/* 个股榜单 */}
          <Section
            title="个股榜单"
            right={
              <div className="flex gap-1">
                {([['gainers', '涨幅'], ['losers', '跌幅'], ['amount', '成交额'], ['turnover', '换手']] as const).map(([k, label]) => (
                  <button
                    key={k}
                    onClick={() => setRankTab(k)}
                    className={`text-xs px-2.5 py-1 rounded transition-colors ${rankTab === k ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800'}`}
                  >{label}</button>
                ))}
              </div>
            }
          >
            <RankTable
              items={review.rankings[rankTab]}
              kind={rankTab === 'amount' ? 'amount' : rankTab === 'turnover' ? 'turnover' : 'pct'}
            />
          </Section>

          {/* 今日市场要闻 */}
          {review.news && review.news.length > 0 && (
            <Section title="📰 今日市场要闻" right={<span className="text-[11px] text-gray-600">{review.news.length} 条</span>}>
              <div className="space-y-2.5">
                {review.news.map((n, i) => {
                  const inner = (
                    <>
                      <div className="flex items-start gap-2">
                        <span className="text-[11px] text-gray-600 font-mono mt-0.5 shrink-0">{String(i + 1).padStart(2, '0')}</span>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm text-gray-200 group-hover:text-blue-300 transition-colors leading-snug">{n.title}</div>
                          {n.summary && <div className="text-xs text-gray-500 mt-0.5 line-clamp-2 leading-relaxed">{n.summary}</div>}
                          <div className="flex items-center gap-2 mt-1 text-[10px] text-gray-600">
                            {n.source && <span className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{n.source}</span>}
                            {n.published && <span>{n.published}</span>}
                          </div>
                        </div>
                      </div>
                    </>
                  )
                  return n.url ? (
                    <a key={i} href={n.url} target="_blank" rel="noreferrer"
                       className="group block border-b border-gray-800/60 pb-2.5 last:border-0 last:pb-0">
                      {inner}
                    </a>
                  ) : (
                    <div key={i} className="group block border-b border-gray-800/60 pb-2.5 last:border-0 last:pb-0">{inner}</div>
                  )
                })}
              </div>
            </Section>
          )}

          <p className="text-center text-[11px] text-gray-600 pt-1">
            数据于 {new Date(review.generated_at).toLocaleString('zh-CN')} 生成 · 仅供复盘参考，不构成投资建议
          </p>
        </div>
      )}
    </div>
  )
}
