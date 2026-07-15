import { useState, useEffect, useCallback, useRef } from 'react'
import WatchlistButton from '../components/WatchlistButton'

interface StockItem {
  symbol: string; name: string; pct: number; price: number
  amount: number; float_mv: number; seal_amount: number
  first_seal: string; last_seal: string; open_times: number
  zt_today: number; zt_total: number; industry: string; note: string
  // Plan B 新增字段
  strong_reason?: string                          // 来自强势池："60日新高" 等
  concepts?: [string, number][]                   // [(概念名, 热度), ...]
  fund_type?: string                              // 推断资金属性
}

interface ConceptGroup {
  concept: string; count: number
  catalyst: string; logic: string
  fund_type: string; continuity: string; continuity_reason: string
  stocks: StockItem[]
  top_concepts?: string[]   // 组内热门概念名列表
}

interface DailyReview {
  trade_date: string; total_zt: number; total_dt: number
  groups: ConceptGroup[]
  dt_stocks: StockItem[]
}

interface DateEntry {
  date: string; total_zt: number; total_dt: number; generated_at: string
}

interface GeneratingStatus {
  running: boolean; started_at: string; progress: string
}

const API = ''

// Format "092500" → "09:25"
function fmtTime(t: string): string {
  if (!t || t.length < 4) return t || '--'
  return `${t.slice(0, 2)}:${t.slice(2, 4)}`
}

// Format yuan → 亿
function fmtYi(v: number): string {
  if (!v) return '--'
  return (v / 1e8).toFixed(2) + '亿'
}

// ── 日历日期选择器 ─────────────────────────────────────────────────────────
interface CalendarProps {
  value: string                       // YYYY-MM-DD 当前选中
  today: string                       // YYYY-MM-DD 今日
  datesWithData: Set<string>          // 已有数据的日期集合
  onSelect: (date: string) => void    // 选中已有数据的日期
  onGenerate: (date: string) => void  // 点缺数据的日期 → 触发生成
  generating: boolean
}

function DateCalendar({ value, today, datesWithData, onSelect, onGenerate, generating }: CalendarProps) {
  // 当前显示的月份
  const [viewMonth, setViewMonth] = useState(() => {
    const base = value || today
    const d = new Date(base)
    return new Date(d.getFullYear(), d.getMonth(), 1)
  })
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  // 点外部关闭
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // 计算月份网格
  const year = viewMonth.getFullYear()
  const month = viewMonth.getMonth()
  const firstDay = new Date(year, month, 1)
  const startWeekday = firstDay.getDay()  // 0=日
  const daysInMonth = new Date(year, month + 1, 0).getDate()

  // 生成 6 行 × 7 列的网格
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

  const monthLabel = `${year}年${month + 1}月`

  const handleCellClick = (dStr: string) => {
    if (isWeekend(dStr) || dStr > today) return
    if (datesWithData.has(dStr)) {
      onSelect(dStr)
      setOpen(false)
    } else {
      onGenerate(dStr)
      setOpen(false)
    }
  }

  return (
    <div ref={wrapperRef} className="relative">
      {/* 触发按钮 */}
      <button
        onClick={() => setOpen(!open)}
        className="bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 flex items-center gap-2 min-w-[160px]"
      >
        <span>📅</span>
        <span className="font-mono">{value || today}</span>
        {datesWithData.has(value) && <span className="text-[10px] text-green-400">●</span>}
        <span className="ml-auto text-gray-500">▾</span>
      </button>

      {/* 弹出日历 */}
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl p-3 z-50 w-[280px]">
          {/* 月份头 */}
          <div className="flex items-center justify-between mb-2">
            <button
              onClick={() => setViewMonth(new Date(year, month - 1, 1))}
              className="text-gray-400 hover:text-white p-1 hover:bg-gray-800 rounded"
            >‹</button>
            <span className="text-sm font-semibold text-white">{monthLabel}</span>
            <button
              onClick={() => setViewMonth(new Date(year, month + 1, 1))}
              className="text-gray-400 hover:text-white p-1 hover:bg-gray-800 rounded"
            >›</button>
          </div>

          {/* 周表头 */}
          <div className="grid grid-cols-7 gap-1 mb-1">
            {['日', '一', '二', '三', '四', '五', '六'].map((w, i) => (
              <div key={w} className={`text-[10px] text-center font-medium ${i === 0 || i === 6 ? 'text-gray-600' : 'text-gray-400'}`}>
                {w}
              </div>
            ))}
          </div>

          {/* 日期格子 */}
          <div className="grid grid-cols-7 gap-1">
            {cells.map((cell, i) => {
              if (!cell.date) return <div key={i} />
              const dStr = cell.date
              const isWE = isWeekend(dStr)
              const isFuture = dStr > today
              const isSelected = dStr === value
              const isToday = dStr === today
              const hasData = datesWithData.has(dStr)

              const baseCls = "h-8 text-xs rounded flex items-center justify-center font-mono transition-colors relative"

              if (isFuture) {
                return <div key={i} className={`${baseCls} text-gray-700`}>{cell.day}</div>
              }
              if (isWE) {
                return <div key={i} className={`${baseCls} text-gray-700`}>{cell.day}</div>
              }
              if (hasData) {
                return (
                  <button
                    key={i}
                    onClick={() => handleCellClick(dStr)}
                    className={`${baseCls} ${
                      isSelected ? 'bg-blue-600 text-white' :
                      'bg-green-900/50 text-green-300 hover:bg-green-800/70'
                    } ${isToday ? 'ring-1 ring-amber-400' : ''}`}
                    title={`${dStr} 已有数据，点击查看`}
                  >
                    {cell.day}
                    <span className="absolute bottom-0.5 right-1 w-1 h-1 rounded-full bg-green-400" />
                  </button>
                )
              }
              return (
                <button
                  key={i}
                  onClick={() => handleCellClick(dStr)}
                  disabled={generating}
                  className={`${baseCls} ${
                    isSelected ? 'bg-blue-600 text-white' :
                    'bg-gray-800 text-gray-500 hover:bg-red-900/40 hover:text-red-300'
                  } ${isToday ? 'ring-1 ring-amber-400' : ''} ${generating ? 'opacity-40 cursor-wait' : ''}`}
                  title={isToday ? '今日待生成，点击触发' : `${dStr} 暂无数据，点击触发后台生成`}
                >
                  {cell.day}
                </button>
              )
            })}
          </div>

          {/* 图例 */}
          <div className="flex items-center gap-3 mt-3 pt-2 border-t border-gray-800 text-[10px] text-gray-500">
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded bg-green-900/50 border border-green-700"/>已有
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded bg-gray-800 border border-gray-700"/>未生成
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded bg-blue-600"/>当前
            </span>
          </div>
          <p className="text-[10px] text-gray-600 mt-1.5 leading-relaxed">
            💡 点已有数据查看 · 点未生成日期自动后台补齐（约2-3分钟）
          </p>
        </div>
      )}
    </div>
  )
}


function BoardBadge({ n }: { n: number }) {
  // 高板特殊高亮（5板以上=妖股级，渐变红）
  const base = "inline-flex items-center justify-center min-w-[32px] h-5 px-1.5 rounded text-[11px] font-bold whitespace-nowrap leading-none"
  if (n >= 7) return <span className={`${base} bg-gradient-to-r from-red-700 to-pink-600 text-white border border-red-400 shadow-sm shadow-red-500/40`}>{n}连板</span>
  if (n >= 5) return <span className={`${base} bg-red-700 text-white border border-red-500`}>{n}连板</span>
  if (n === 4) return <span className={`${base} bg-red-600 text-white`}>4连板</span>
  if (n === 3) return <span className={`${base} bg-orange-600 text-white`}>3连板</span>
  if (n === 2) return <span className={`${base} bg-orange-500 text-white`}>2连板</span>
  return <span className={`${base} bg-gray-700 text-gray-300 font-medium`}>首板</span>
}

function ContinuityBadge({ c, reason }: { c: string; reason: string }) {
  const cls =
    c === '强' ? 'bg-green-900 text-green-300 border-green-700' :
    c === '中' ? 'bg-yellow-900 text-yellow-300 border-yellow-700' :
    'bg-gray-800 text-gray-400 border-gray-600'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border ${cls}`} title={reason}>
      持续性：{c}
    </span>
  )
}

function FundBadge({ t }: { t: string }) {
  const cls =
    t === '游资主导' ? 'bg-purple-900 text-purple-300 border-purple-700' :
    t === '机构主导' ? 'bg-blue-900 text-blue-300 border-blue-700' :
    'bg-indigo-900 text-indigo-300 border-indigo-700'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs border ${cls}`}>
      {t || '未知'}
    </span>
  )
}

function StrongBadge({ reason }: { reason?: string }) {
  if (!reason) return null
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-amber-900/60 text-amber-300 border border-amber-700/60 whitespace-nowrap">
      {reason}
    </span>
  )
}

function ConceptTags({ concepts }: { concepts?: [string, number][] }) {
  if (!concepts || concepts.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {concepts.slice(0, 2).map(([name, heat]) => (
        <span key={name} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-gray-800 text-gray-400 border border-gray-700">
          {name}
          <span className="text-gray-600 text-[9px]">{heat.toFixed(0)}</span>
        </span>
      ))}
    </div>
  )
}

function ConceptCard({ group, defaultExpanded }: { group: ConceptGroup; defaultExpanded: boolean }) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden mb-3">
      {/* Header */}
      <button
        className="w-full flex items-center gap-3 px-4 py-3 bg-gray-800/70 hover:bg-gray-800 transition-colors text-left"
        onClick={() => setExpanded(e => !e)}
      >
        <span className="text-red-400 font-bold text-base whitespace-nowrap">
          {group.concept} × {group.count}
        </span>
        {/* 板块热门概念标签 */}
        {group.top_concepts && group.top_concepts.length > 0 && (
          <div className="flex items-center gap-1 flex-shrink-0">
            {group.top_concepts.slice(0, 3).map(c => (
              <span key={c} className="px-1.5 py-0.5 rounded text-[10px] bg-purple-900/50 text-purple-300 border border-purple-800/60 whitespace-nowrap">
                {c}
              </span>
            ))}
          </div>
        )}
        {group.catalyst && (
          <span className="text-gray-400 text-xs truncate flex-1 hidden md:block" title={group.catalyst}>
            {group.catalyst}
          </span>
        )}
        <div className="flex items-center gap-2 shrink-0">
          <FundBadge t={group.fund_type} />
          <ContinuityBadge c={group.continuity} reason={group.continuity_reason} />
          <span className="text-gray-500 text-xs ml-1">{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {expanded && (
        <div>
          {/* Catalyst + Logic */}
          {(group.catalyst || group.logic) && (
            <div className="px-4 py-2 bg-gray-900/60 border-b border-gray-800 space-y-1">
              {group.catalyst && (
                <p className="text-yellow-400/80 text-xs font-medium">{group.catalyst}</p>
              )}
              {group.logic && (
                <p className="text-gray-400 text-xs leading-relaxed">{group.logic}</p>
              )}
            </div>
          )}

          {/* Stock table */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900/40">
                  <th className="px-3 py-2 text-left text-gray-500 font-normal w-20">连板</th>
                  <th className="px-3 py-2 text-left text-gray-500 font-normal">代码/名称</th>
                  <th className="px-3 py-2 text-right text-gray-500 font-normal">价格</th>
                  <th className="px-3 py-2 text-right text-gray-500 font-normal">流通市值</th>
                  <th className="px-3 py-2 text-right text-gray-500 font-normal">封板资金</th>
                  <th className="px-3 py-2 text-center text-gray-500 font-normal">首封/炸板</th>
                  <th className="px-3 py-2 text-left text-gray-500 font-normal">特征 / 热门概念</th>
                </tr>
              </thead>
              <tbody>
                {group.stocks.map(s => (
                  <tr key={s.symbol} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                    <td className="px-3 py-2">
                      <BoardBadge n={s.zt_today} />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <WatchlistButton code={s.symbol} name={s.name} />
                        <span className="font-medium text-gray-200">{s.name}</span>
                        <span className="font-mono text-gray-500 text-[10px]">{s.symbol}</span>
                        {s.strong_reason && <StrongBadge reason={s.strong_reason} />}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right text-red-400 font-mono">{s.price.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right text-gray-400">{fmtYi(s.float_mv)}</td>
                    <td className="px-3 py-2 text-right text-yellow-400">{fmtYi(s.seal_amount)}</td>
                    <td className="px-3 py-2 text-center">
                      <div className="flex flex-col items-center gap-0.5">
                        <span className="text-gray-400">{fmtTime(s.first_seal)}</span>
                        {s.open_times > 0 && (
                          <span className="text-orange-400 text-[10px]">炸{s.open_times}次</span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <div className="text-gray-400 text-[11px] leading-relaxed">
                        {s.note && <div>{s.note}</div>}
                        <ConceptTags concepts={s.concepts} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function DtSection({ stocks }: { stocks: StockItem[] }) {
  const [expanded, setExpanded] = useState(false)
  if (!stocks || stocks.length === 0) return null

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden mb-3">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 bg-gray-800/40 hover:bg-gray-800/60 transition-colors text-left"
        onClick={() => setExpanded(e => !e)}
      >
        <span className="text-blue-400 font-bold text-base">跌停板 × {stocks.length}</span>
        <span className="text-gray-500 text-xs ml-auto">{expanded ? '▲ 收起' : '▼ 展开'}</span>
      </button>
      {expanded && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900/40">
                <th className="px-3 py-2 text-left text-gray-500 font-normal">代码</th>
                <th className="px-3 py-2 text-left text-gray-500 font-normal">名称</th>
                <th className="px-3 py-2 text-right text-gray-500 font-normal">涨跌幅</th>
                <th className="px-3 py-2 text-right text-gray-500 font-normal">价格</th>
                <th className="px-3 py-2 text-left text-gray-500 font-normal">行业</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map(s => (
                <tr key={s.symbol} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-3 py-2 font-mono text-gray-400">
                    <div className="flex items-center gap-1.5">
                      <WatchlistButton code={s.symbol} name={s.name} />
                      {s.symbol}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-gray-200">{s.name}</td>
                  <td className="px-3 py-2 text-right text-blue-400">{s.pct?.toFixed(2)}%</td>
                  <td className="px-3 py-2 text-right text-gray-400">{s.price?.toFixed(2)}</td>
                  <td className="px-3 py-2 text-gray-500">{s.industry}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function LimitUpReviewPage() {
  const [review, setReview] = useState<DailyReview | null>(null)
  const [dates, setDates] = useState<DateEntry[]>([])
  const [selectedDate, setSelectedDate] = useState<string>('')
  const [status, setStatus] = useState<GeneratingStatus>({ running: false, started_at: '', progress: '' })
  const [message, setMessage] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const today = new Date().toISOString().slice(0, 10)

  const loadDates = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/limitup/dates`)
      const j = await res.json()
      setDates(j.dates || [])
    } catch {}
  }, [])

  const loadReview = useCallback(async (d?: string) => {
    setLoading(true)
    try {
      const url = d ? `${API}/api/limitup/daily?date=${d}` : `${API}/api/limitup/daily`
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
    } catch (e) {
      setMessage('请求失败，请检查后端服务')
    } finally {
      setLoading(false)
    }
  }, [])

  const pollStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/limitup/status`)
      const j = await res.json()
      setStatus(j)
      if (!j.running) {
        if (pollRef.current) {
          clearInterval(pollRef.current)
          pollRef.current = null
        }
        // Refresh data after generation completes
        await loadDates()
        await loadReview(selectedDate || undefined)
      }
    } catch {}
  }, [loadDates, loadReview, selectedDate])

  const startGenerate = useCallback(async (d?: string) => {
    const target = d || today
    try {
      const res = await fetch(`${API}/api/limitup/generate?date=${target}`, { method: 'POST' })
      const j = await res.json()
      setMessage(j.message)
      if (j.ok) {
        setStatus({ running: true, started_at: new Date().toISOString(), progress: '启动中...' })
        // Start polling
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(pollStatus, 3000)
      }
    } catch {
      setMessage('触发失败')
    }
  }, [today, pollStatus])

  // Initial load
  useEffect(() => {
    loadDates()
    loadReview()
  }, [loadDates, loadReview])

  // If status is running on mount (server was already generating), poll
  useEffect(() => {
    if (status.running && !pollRef.current) {
      pollRef.current = setInterval(pollStatus, 3000)
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [status.running, pollStatus])

  const handleDateChange = (d: string) => {
    setSelectedDate(d)
    loadReview(d)
  }

  const isToday = selectedDate === today || (!selectedDate && !review)
  const todayHasData = dates.some(d => d.date === today)

  return (
    <div className="min-h-screen bg-gray-950 text-gray-200 p-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">涨停板复盘</h1>
          <p className="text-xs text-gray-500 mt-0.5">每日自动生成 · 历史永久保存</p>
        </div>

        {/* Date selector (日历) */}
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
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
              status.running
                ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                : 'bg-red-600 hover:bg-red-500 text-white'
            }`}
            title={isToday && !todayHasData ? '生成今日数据' : '重新生成当前日期'}
          >
            {status.running ? '生成中...' : (isToday && !todayHasData ? '🚀 生成今日' : '🔄 重新生成')}
          </button>
        </div>
      </div>

      {/* Status bar */}
      {(status.running || status.progress) && (
        <div className={`mb-4 px-4 py-3 rounded-lg border text-sm ${
          status.running
            ? 'bg-blue-950 border-blue-800 text-blue-300'
            : status.progress.startsWith('失败')
            ? 'bg-red-950 border-red-800 text-red-300'
            : 'bg-green-950 border-green-800 text-green-300'
        }`}>
          <div className="flex items-center gap-2">
            {status.running && (
              <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
            )}
            <span>{status.progress}</span>
          </div>
          {status.running && (
            <div className="mt-2 h-1 bg-blue-900 rounded overflow-hidden">
              <div className="h-full bg-blue-400 animate-pulse w-3/4" />
            </div>
          )}
        </div>
      )}

      {/* Message */}
      {message && !status.running && (
        <div className="mb-4 px-4 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-400">
          {message}
        </div>
      )}

      {/* No data state */}
      {!loading && !review && !status.running && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="text-5xl mb-4">📊</div>
          <p className="text-gray-400 text-lg mb-2">暂无复盘数据</p>
          <p className="text-gray-600 text-sm mb-6">
            {isToday ? '今日复盘尚未生成，每日 15:45 自动触发，或手动点击生成' : '该日期无数据'}
          </p>
          <button
            onClick={() => startGenerate(selectedDate || today)}
            className="px-6 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg font-medium transition-colors"
          >
            立即生成
          </button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-20 text-gray-500">
          <svg className="animate-spin h-6 w-6 mr-2" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
          加载中...
        </div>
      )}

      {/* Review data */}
      {review && !loading && (
        <>
          {/* Summary stats */}
          <div className="flex flex-wrap items-center gap-4 mb-5 px-4 py-3 bg-gray-900 rounded-lg border border-gray-800">
            <div>
              <span className="text-gray-500 text-xs">日期</span>
              <p className="text-white font-bold">{review.trade_date}</p>
            </div>
            <div className="w-px h-8 bg-gray-800" />
            <div>
              <span className="text-gray-500 text-xs">涨停总数</span>
              <p className="text-red-400 font-bold text-xl">{review.total_zt}</p>
            </div>
            <div className="w-px h-8 bg-gray-800" />
            <div>
              <span className="text-gray-500 text-xs">跌停总数</span>
              <p className="text-blue-400 font-bold text-xl">{review.total_dt}</p>
            </div>
            <div className="w-px h-8 bg-gray-800" />
            <div>
              <span className="text-gray-500 text-xs">板块数</span>
              <p className="text-gray-200 font-bold text-xl">{review.groups?.length || 0}</p>
            </div>
          </div>

          {/* Concept groups */}
          <div>
            {review.groups?.map((group, i) => (
              <ConceptCard
                key={group.concept}
                group={group}
                defaultExpanded={i < 3}
              />
            ))}
          </div>

          {/* DT section */}
          {review.dt_stocks && review.dt_stocks.length > 0 && (
            <DtSection stocks={review.dt_stocks} />
          )}
        </>
      )}
    </div>
  )
}
