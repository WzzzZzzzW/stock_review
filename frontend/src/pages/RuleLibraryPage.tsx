/**
 * 规则库 —— 自定义选股规则库
 * 每条规则 = 一组结构化筛选条件（可叠加、AND/OR、可排除 ST/科创/创业/北交所）。
 * 支持：结构化条件搭建 + 一句话 AI 解析；命名、收藏；点开一条规则即实时筛选全市场股票。
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import WatchlistButton from '../components/WatchlistButton'

// ── 类型 ────────────────────────────────────────────────────────────────────
interface Field { key: string; label: string; unit: string; scale: number; decimals: number }
interface Operator { key: string; label: string }
interface Condition { field: string; op: string; value: number | '' ; value2?: number | '' }
interface Universe { exclude_st?: boolean; exclude_688?: boolean; exclude_300?: boolean; exclude_bj?: boolean; [key: string]: boolean | undefined }
interface Pattern { key: string; label: string; hint: string }
interface Rule {
  id: string; name: string; conditions: Condition[]; logic: string
  universe: Universe; nl_source: string; sort_field: string; sort_dir: string
  favorite: boolean; created_at: string; updated_at: string
  source: string; kind: string; theme: string; why: string; auto_date: string
}
interface AutoStatus {
  running: boolean
  last_run?: { ok: boolean; at: string; message: string; count?: number } | null
}
interface StockRow {
  symbol: string; name: string; price: number | null; change_pct: number | null
  turnover: number | null; pe: number | null; pb: number | null
  market_cap: number | null; float_cap: number | null; amount: number | null
  amplitude: number | null; volume: number | null; volume_ratio: number | null
  industry?: string | null
}
// 结果表下拉详情（懒加载 /api/screen-rule/detail/{symbol}）
interface StockDetail {
  symbol: string
  industry: string | null
  business: { business: string; products: string; scope: string } | null
  recent: {
    date: string | null; pct_change: number | null; tags: string[]
    streak: number | null; above_ma5: boolean; above_ma20: boolean; above_ma60: boolean
    ma5_pct: number | null; ma20_pct: number | null; ma60_pct: number | null
    macd_status: string | null; rsi14: number | null; vol_ratio: number | null
  } | null
}
interface RunResult { rule?: Rule; total: number; stocks: StockRow[]; generated_at: string; theme?: string; theme_ok?: boolean }

const OP_SYMBOL: Record<string, string> = { gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', between: '区间' }
const UNIVERSE_LABELS: { key: keyof Universe; label: string }[] = [
  { key: 'exclude_st', label: '排除 ST' },
  { key: 'exclude_688', label: '排除科创板' },
  { key: 'exclude_300', label: '排除创业板' },
  { key: 'exclude_bj', label: '排除北交所' },
]
// 形态条件（需多日历史日线，作为候选集后置过滤；与数值字段不同，单独成组）
// 默认值与后端 screen_service.PATTERNS 对齐，作为 /fields 未返回时的兜底；运行时以后端为准。
const DEFAULT_PATTERNS: Pattern[] = [
  { key: 'vol_uptrend', label: '成交量温和放大', hint: '近 5 日成交量台阶式逐步放大（温和、无暴量）' },
  { key: 'ma_bullish', label: '均线多头排列', hint: 'MA5 > MA20 > MA60，且收盘站上 MA5' },
  { key: 'above_ma20', label: '站上20日线', hint: '最新收盘价在 20 日均线之上' },
  { key: 'macd_golden', label: 'MACD金叉', hint: '今日 MACD 由负转正（DIF 上穿 DEA）' },
  { key: 'new_high_60', label: '创60日新高', hint: '最新收盘价创近 60 个交易日新高' },
  { key: 'streak_up', label: '连涨3天以上', hint: '最近连续 3 个交易日收阳' },
]

// ── 颜色/格式工具（A股：红涨绿跌）────────────────────────────────────────────
function pctColor(v: number | null | undefined) {
  if (v === null || v === undefined) return 'text-gray-500'
  if (v > 0) return 'text-red-400'
  if (v < 0) return 'text-green-400'
  return 'text-gray-400'
}
const fmtPct = (v: number | null | undefined) => (v === null || v === undefined ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
const fmtNum = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? '--' : v.toFixed(d))

// ── 条件→文字 ────────────────────────────────────────────────────────────────
function condText(c: Condition, fmap: Record<string, Field>) {
  const f = fmap[c.field]
  if (!f) return ''
  if (c.op === 'between') return `${f.label} ${c.value}~${c.value2}${f.unit}`
  return `${f.label} ${OP_SYMBOL[c.op] || c.op} ${c.value}${f.unit}`
}

// ── 清洗条件（去掉值未填的）──────────────────────────────────────────────────
function cleanConditions(conds: Condition[]): Condition[] {
  return conds.filter(c => {
    if (!c.field || !c.op) return false
    if (c.value === '' || c.value === null || c.value === undefined) return false
    if (c.op === 'between' && (c.value2 === '' || c.value2 === null || c.value2 === undefined)) return false
    return true
  }).map(c => c.op === 'between'
    ? { field: c.field, op: c.op, value: Number(c.value), value2: Number(c.value2) }
    : { field: c.field, op: c.op, value: Number(c.value) })
}

// ══════════════════════════════════════════════════════════════════════════════
export default function RuleLibraryPage({ onSelectStock }: { onSelectStock?: (symbol: string, name: string) => void }) {
  const [fields, setFields] = useState<Field[]>([])
  const [operators, setOperators] = useState<Operator[]>([])
  const [patterns, setPatterns] = useState<Pattern[]>(DEFAULT_PATTERNS)
  const [rules, setRules] = useState<Rule[]>([])
  const [selectedId, setSelectedId] = useState<string>('')
  const [result, setResult] = useState<RunResult | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState(false)
  // 筛选完成后批量预取的下拉详情（按 symbol 缓存，点开即显示，无需再等待）
  const [detailMap, setDetailMap] = useState<Record<string, StockDetail>>({})
  // 回测弹窗
  const [btRule, setBtRule] = useState<Rule | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editRule, setEditRule] = useState<Rule | null>(null)
  const [autoStatus, setAutoStatus] = useState<AutoStatus | null>(null)
  const [pushing, setPushing] = useState(false)

  const fmap: Record<string, Field> = {}
  fields.forEach(f => { fmap[f.key] = f })

  const autoRules = rules.filter(r => r.source === 'auto')
  const userRules = rules.filter(r => r.source !== 'auto')

  // ── 加载字段元数据 + 规则列表 ──
  const loadFields = useCallback(async () => {
    try {
      const r = await fetch('/api/screen-rule/fields')
      const j = await r.json()
      setFields(j.fields || [])
      setOperators(j.operators || [])
      if (Array.isArray(j.patterns) && j.patterns.length) setPatterns(j.patterns)
    } catch { /* ignore */ }
  }, [])

  const loadRules = useCallback(async () => {
    try {
      const r = await fetch('/api/screen-rule/rules')
      const j = await r.json()
      setRules(j.rules || [])
      return (j.rules || []) as Rule[]
    } catch { return [] }
  }, [])

  const loadAutoStatus = useCallback(async () => {
    try {
      const r = await fetch('/api/screen-rule/auto/status')
      const j = await r.json()
      setAutoStatus(j)
      return j as AutoStatus
    } catch { return null }
  }, [])

  useEffect(() => { loadFields(); loadRules(); loadAutoStatus() }, [loadFields, loadRules, loadAutoStatus])

  // 生成推送时轮询状态，跑完自动刷新规则列表
  useEffect(() => {
    if (!pushing) return
    const t = setInterval(async () => {
      const st = await loadAutoStatus()
      if (st && !st.running) {
        setPushing(false)
        loadRules()
      }
    }, 4000)
    return () => clearInterval(t)
  }, [pushing, loadAutoStatus, loadRules])

  const refreshPush = async () => {
    if (pushing) return
    setPushing(true)
    try {
      await fetch('/api/screen-rule/auto/generate', { method: 'POST' })
    } catch { setPushing(false) }
  }

  const saveAsMine = async (rid: string, e: React.MouseEvent) => {
    e.stopPropagation()
    await fetch(`/api/screen-rule/rules/${rid}/save-as-mine`, { method: 'POST' })
    loadRules()
  }

  // ── 运行某条规则 ──
  const runRule = useCallback(async (rid: string) => {
    setSelectedId(rid)
    setRunning(true)
    setResult(null)
    setRunError(false)
    setDetailMap({})   // 换规则/重跑先清空旧详情缓存
    try {
      const r = await fetch(`/api/screen-rule/rules/${rid}/run?limit=300`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const j = await r.json()
      setResult(j)
      // 后台批量预取下拉详情（封顶前 30 只，一次 baostock 会话），点开即显示
      const syms: string[] = (j.stocks || []).slice(0, 30).map((x: StockRow) => x.symbol)
      if (syms.length) {
        fetch('/api/screen-rule/detail-batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbols: syms }),
        })
          .then(res => res.ok ? res.json() : null)
          .then(data => { if (data?.details) setDetailMap(prev => ({ ...prev, ...data.details })) })
          .catch(() => { /* 预取失败不影响：点开时回退到单只懒加载 */ })
      }
    } catch {
      setResult(null)
      setRunError(true)
    } finally {
      setRunning(false)
    }
  }, [])

  const toggleFav = async (rid: string, e: React.MouseEvent) => {
    e.stopPropagation()
    await fetch(`/api/screen-rule/rules/${rid}/favorite`, { method: 'POST' })
    loadRules()
  }

  const removeRule = async (rid: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('确定删除这条规则？')) return
    await fetch(`/api/screen-rule/rules/${rid}`, { method: 'DELETE' })
    if (selectedId === rid) { setSelectedId(''); setResult(null) }
    loadRules()
  }

  const openCreate = () => { setEditRule(null); setModalOpen(true) }
  const openEdit = (rule: Rule, e: React.MouseEvent) => { e.stopPropagation(); setEditRule(rule); setModalOpen(true) }

  const onSaved = async (savedId: string) => {
    setModalOpen(false)
    await loadRules()
    runRule(savedId)
  }

  const selectedRule = rules.find(r => r.id === selectedId)

  // ── 单条规则卡片（推送卡与我的规则卡共用，按 isAuto 切换操作按钮）──
  const renderCard = (rule: Rule, isAuto: boolean) => (
    <div
      key={rule.id}
      onClick={() => runRule(rule.id)}
      className={`group cursor-pointer rounded-xl border p-3 transition-all ${
        selectedId === rule.id
          ? 'bg-blue-600/15 border-blue-500/60'
          : isAuto
            ? 'bg-indigo-950/30 border-indigo-900/50 hover:border-indigo-700/70 hover:bg-indigo-900/20'
            : 'bg-gray-900 border-gray-800 hover:border-gray-700 hover:bg-gray-800/50'
      }`}
    >
      <div className="flex items-center gap-2">
        {isAuto ? (
          <span className="text-base leading-none" title="每日推送">🤖</span>
        ) : (
          <button
            onClick={(e) => toggleFav(rule.id, e)}
            className={`text-base leading-none transition-transform hover:scale-110 ${rule.favorite ? 'text-amber-400' : 'text-gray-600 hover:text-gray-400'}`}
            title={rule.favorite ? '取消收藏' : '收藏'}
          >{rule.favorite ? '★' : '☆'}</button>
        )}
        <span className="font-medium text-sm text-white truncate flex-1">{rule.name}</span>
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
          {isAuto ? (
            <button onClick={(e) => saveAsMine(rule.id, e)} className="text-gray-500 hover:text-amber-400 text-xs px-1" title="保存为我的（避免明日刷新清掉）">📌</button>
          ) : (
            <button onClick={(e) => openEdit(rule, e)} className="text-gray-500 hover:text-blue-400 text-xs px-1" title="编辑">✎</button>
          )}
          <button onClick={(e) => removeRule(rule.id, e)} className="text-gray-500 hover:text-red-400 text-xs px-1" title={isAuto ? '不感兴趣' : '删除'}>🗑</button>
        </div>
      </div>
      {rule.kind === 'theme' && rule.theme && (
        <div className="mt-1.5">
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/40 text-purple-300 border border-purple-800/40">题材 · {rule.theme}</span>
        </div>
      )}
      {isAuto && rule.why && (
        <p className="mt-1.5 text-[11px] text-gray-400 leading-snug line-clamp-2">{rule.why}</p>
      )}
      <div className="mt-1.5 flex flex-wrap gap-1">
        {rule.conditions.slice(0, 4).map((c, i) => (
          <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 whitespace-nowrap">
            {condText(c, fmap)}
          </span>
        ))}
        {rule.conditions.length === 0 && rule.kind !== 'theme' && <span className="text-[10px] text-gray-600">全市场（无条件）</span>}
        {rule.conditions.length === 0 && rule.kind === 'theme' && <span className="text-[10px] text-gray-600">该题材全部成分股</span>}
        {rule.conditions.length > 4 && <span className="text-[10px] text-gray-600">+{rule.conditions.length - 4}</span>}
      </div>
    </div>
  )

  const lastPushAt = autoStatus?.last_run?.at ? autoStatus.last_run.at.slice(5, 16).replace('T', ' ') : ''

  return (
    <div className="min-h-screen bg-gray-950 text-gray-200">
      <div className="max-w-7xl mx-auto p-4">
        {/* 标题 */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-xl font-bold text-white">🎯 规则库</h1>
            <p className="text-xs text-gray-500 mt-0.5">自定义选股规则 · 点开一条即按你的条件实时筛选全市场</p>
          </div>
          <button
            onClick={openCreate}
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-xl shadow-lg shadow-blue-600/30 transition-colors"
          >+ 新建规则</button>
        </div>

        <div className="flex flex-col lg:flex-row gap-4">
          {/* ── 左：规则列表（我的在上 + 推送在下，分区）── */}
          <aside className="lg:w-72 shrink-0 space-y-2">
            {/* 我的规则区 */}
            <div className="flex items-center justify-between px-1 pt-1">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold text-gray-300">⭐ 我的规则</span>
                {userRules.length > 0 && <span className="text-[10px] text-gray-600">{userRules.length}</span>}
              </div>
              <button onClick={openCreate} className="text-[11px] text-gray-400 hover:text-white border border-gray-700 rounded-lg px-2 py-0.5 transition-colors">+ 新建</button>
            </div>
            {userRules.length === 0 && (
              <div className="bg-gray-900 border border-dashed border-gray-700 rounded-xl p-4 text-center">
                <p className="text-xs text-gray-400">还没有自建规则</p>
                <p className="text-[11px] text-gray-600 mt-1">「新建」搭一条，或把喜欢的推送 📌 保存过来</p>
              </div>
            )}
            {userRules.map(rule => renderCard(rule, false))}

            {/* 每日推送区 */}
            <div className="flex items-center justify-between px-1 pt-3">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold text-indigo-300">🤖 每日推送</span>
                {autoRules.length > 0 && <span className="text-[10px] text-gray-600">{autoRules.length}</span>}
              </div>
              <button
                onClick={refreshPush}
                disabled={pushing}
                className="text-[11px] text-indigo-300 hover:text-indigo-200 border border-indigo-800/60 rounded-lg px-2 py-0.5 transition-colors disabled:opacity-50"
                title="重新读今日新闻+行业生成推送规则"
              >{pushing ? '生成中…' : '↻ 刷新'}</button>
            </div>
            {lastPushAt && (
              <p className="px-1 text-[10px] text-gray-600 -mt-1">更新于 {lastPushAt}</p>
            )}
            {pushing && (
              <div className="bg-indigo-950/30 border border-indigo-900/50 rounded-xl p-4 text-center">
                <p className="text-xs text-indigo-300">正在读今日新闻与行业表现，<br/>AI 生成推送规则（约 1 分钟）…</p>
              </div>
            )}
            {!pushing && autoRules.length === 0 && (
              <div className="bg-indigo-950/20 border border-dashed border-indigo-900/50 rounded-xl p-4 text-center">
                <p className="text-xs text-gray-400">今日还没有推送规则</p>
                <p className="text-[11px] text-gray-600 mt-1">点上方「↻ 刷新」让 AI 现在生成</p>
              </div>
            )}
            {autoRules.map(rule => renderCard(rule, true))}
          </aside>

          {/* ── 右：筛选结果 ── */}
          <main className="flex-1 min-w-0">
            {!selectedRule && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center">
                <div className="text-4xl mb-3">👈</div>
                <p className="text-gray-400 text-sm">从左侧选一条规则查看它帮你筛出的股票</p>
                <p className="text-gray-600 text-xs mt-1">还没有规则？点右上角「新建规则」</p>
              </div>
            )}

            {selectedRule && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                {/* 头部：规则名 + 条件 + 计数 */}
                <div className="p-4 border-b border-gray-800">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2">
                      {selectedRule.source === 'auto' && <span title="每日推送">🤖</span>}
                      {selectedRule.favorite && <span className="text-amber-400">★</span>}
                      <h2 className="text-base font-bold text-white">{selectedRule.name}</h2>
                      <span className="text-xs text-gray-500">
                        {selectedRule.logic === 'OR' ? '满足任一' : '同时满足'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {result && <span className="text-sm text-blue-400 font-mono">{result.total} 只</span>}
                      <button onClick={() => runRule(selectedRule.id)} className="text-xs text-gray-400 hover:text-white border border-gray-700 rounded-lg px-2.5 py-1 transition-colors">🔄 刷新</button>
                      <button onClick={() => setBtRule(selectedRule)} className="text-xs text-emerald-300 hover:text-emerald-200 border border-emerald-800/60 rounded-lg px-2.5 py-1 transition-colors" title="用历史日K真回测：每周再平衡，等权持仓，和大盘对比">📊 回测</button>
                      {selectedRule.source === 'auto'
                        ? <button onClick={(e) => saveAsMine(selectedRule.id, e)} className="text-xs text-amber-300 hover:text-amber-200 border border-amber-800/60 rounded-lg px-2.5 py-1 transition-colors" title="保存到「我的规则」，避免明日刷新被清掉">📌 保存为我的</button>
                        : <button onClick={(e) => openEdit(selectedRule, e)} className="text-xs text-gray-400 hover:text-white border border-gray-700 rounded-lg px-2.5 py-1 transition-colors">✎ 编辑</button>}
                    </div>
                  </div>
                  {selectedRule.why && (
                    <p className="mt-2 text-xs text-indigo-200/80 bg-indigo-950/30 border border-indigo-900/40 rounded-lg px-3 py-1.5 leading-relaxed">💡 {selectedRule.why}</p>
                  )}
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {selectedRule.kind === 'theme' && selectedRule.theme && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-purple-900/40 text-purple-200 border border-purple-700/50">题材 · {selectedRule.theme}</span>
                    )}
                    {selectedRule.conditions.map((c, i) => (
                      <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-blue-900/30 text-blue-300 border border-blue-800/40">{condText(c, fmap)}</span>
                    ))}
                    {patterns.filter(p => selectedRule.universe[p.key]).map(p => (
                      <span key={p.key} title={p.hint} className="text-xs px-2 py-0.5 rounded-full bg-amber-900/30 text-amber-300 border border-amber-700/50">📈 {p.label}</span>
                    ))}
                    {UNIVERSE_LABELS.filter(u => selectedRule.universe[u.key]).map(u => (
                      <span key={u.key} className="text-xs px-2 py-0.5 rounded-full bg-gray-800 text-gray-400 border border-gray-700">{u.label}</span>
                    ))}
                    {selectedRule.conditions.length === 0 && !patterns.some(p => selectedRule.universe[p.key]) && selectedRule.kind !== 'theme' && <span className="text-xs text-gray-600">无条件（全市场）</span>}
                  </div>
                </div>

                {/* 结果表 */}
                {running && (
                  <div className="flex flex-col items-center justify-center py-16 text-gray-500 text-sm">
                    <div className="flex items-center">
                      <svg className="animate-spin h-5 w-5 mr-2" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      正在全市场筛选...
                    </div>
                    {patterns.some(p => selectedRule.universe[p.key]) && (
                      <span className="mt-2 text-xs text-amber-200/70">
                        含形态条件（{patterns.filter(p => selectedRule.universe[p.key]).map(p => p.label).join('、')}），首次需逐只拉取历史日线，约 10–30 秒，请稍候（之后当日缓存，秒开）
                      </span>
                    )}
                  </div>
                )}

                {!running && runError && (
                  <div className="py-16 text-center text-gray-500 text-sm">
                    筛选出错了，可能是数据源波动或首次拉取历史超时<br/>
                    <button onClick={() => runRule(selectedRule.id)} className="mt-2 text-xs text-blue-400 hover:text-blue-300 border border-blue-800/50 rounded-lg px-3 py-1">↻ 点此重试</button>
                  </div>
                )}

                {!running && result && result.theme_ok === false && (
                  <div className="py-16 text-center text-gray-500 text-sm">
                    题材「{result.theme}」成分股暂时拉取失败<br/>
                    <span className="text-xs text-gray-600">数据源偶发波动，点上方「🔄 刷新」再试一次</span>
                  </div>
                )}

                {!running && result && result.theme_ok !== false && result.stocks.length === 0 && (
                  <div className="py-16 text-center text-gray-500 text-sm">没有股票符合当前条件，试试放宽一些</div>
                )}

                {!running && result && result.stocks.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-xs text-gray-500 border-b border-gray-800">
                          <th className="text-left px-3 py-2 font-normal">#</th>
                          <th className="text-left px-3 py-2 font-normal">名称</th>
                          <th className="text-left px-3 py-2 font-normal hidden sm:table-cell">行业</th>
                          <th className="text-right px-3 py-2 font-normal">现价</th>
                          <th className="text-right px-3 py-2 font-normal">涨跌幅</th>
                          <th className="text-right px-3 py-2 font-normal hidden sm:table-cell">换手%</th>
                          <th className="text-right px-3 py-2 font-normal hidden md:table-cell">量比</th>
                          <th className="text-right px-3 py-2 font-normal hidden lg:table-cell">振幅%</th>
                          <th className="text-right px-3 py-2 font-normal">总市值亿</th>
                          <th className="text-center px-2 py-2 font-normal w-8" />
                        </tr>
                      </thead>
                      <tbody>
                        {result.stocks.map((s, i) => (
                          <ResultRow key={s.symbol} s={s} index={i} onSelectStock={onSelectStock} prefetched={detailMap[s.symbol]} />
                        ))}
                      </tbody>
                    </table>
                    {result.total > result.stocks.length && (
                      <div className="px-3 py-2 text-center text-xs text-gray-600 border-t border-gray-800">
                        共 {result.total} 只，已显示前 {result.stocks.length} 只（按{fmap[selectedRule.sort_field]?.label || '涨跌幅'}{selectedRule.sort_dir === 'asc' ? '升序' : '降序'}）
                      </div>
                    )}
                    <div className="px-3 py-2 text-center text-[11px] text-gray-600 border-t border-gray-800/60">
                      数据时间 {result.generated_at} · 点击任意股票跳转个股复盘 · 仅供研究参考
                    </div>
                  </div>
                )}
              </div>
            )}
          </main>
        </div>
      </div>

      {modalOpen && (
        <RuleEditor
          fields={fields}
          operators={operators}
          patterns={patterns}
          rule={editRule}
          onClose={() => setModalOpen(false)}
          onSaved={onSaved}
        />
      )}

      {btRule && (
        <BacktestModal rule={btRule} onClose={() => setBtRule(null)} />
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// 新建 / 编辑规则弹窗
// ══════════════════════════════════════════════════════════════════════════════
// ── 结果表单行：主行可点跳复盘 + 可展开详情（懒加载 行业/主营业务/最近表现）──────
function ResultRow({ s, index, onSelectStock, prefetched }: {
  s: StockRow; index: number; onSelectStock?: (symbol: string, name: string) => void
  prefetched?: StockDetail
}) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<StockDetail | null>(prefetched ?? null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

  // 预取数据稍后到达时同步进来（点开前/后都能即时显示）
  useEffect(() => { if (prefetched) setDetail(prefetched) }, [prefetched])

  const loadAndToggle = () => {
    const next = !open
    setOpen(next)
    // 已有预取/已加载数据则点开即显示；否则回退到单只懒加载
    if (next && !detail && !loading) {
      setLoading(true); setFailed(false)
      fetch(`/api/screen-rule/detail/${s.symbol}`)
        .then(r => r.json())
        .then((d: StockDetail) => setDetail(d))
        .catch(() => setFailed(true))
        .finally(() => setLoading(false))
    }
  }

  const ind = s.industry || detail?.industry || ''
  const r = detail?.recent
  const biz = detail?.business

  return (
    <>
      <tr
        onClick={() => onSelectStock?.(s.symbol, s.name)}
        className="border-t border-gray-800/40 hover:bg-gray-800/40 cursor-pointer transition-colors"
      >
        <td className="px-3 py-2 text-gray-600 tabular-nums text-xs">{index + 1}</td>
        <td className="px-3 py-2">
          <div className="flex items-center gap-1.5">
            <WatchlistButton code={s.symbol} name={s.name} />
            <div>
              <div className="text-gray-200">{s.name}</div>
              <div className="text-[11px] text-gray-600 font-mono">{s.symbol}</div>
            </div>
          </div>
        </td>
        <td className="px-3 py-2 hidden sm:table-cell">
          <span className="text-xs text-gray-400 truncate inline-block max-w-[7.5rem] align-middle" title={ind}>{ind || '--'}</span>
        </td>
        <td className="px-3 py-2 text-right font-mono text-gray-300">{fmtNum(s.price)}</td>
        <td className={`px-3 py-2 text-right font-mono font-semibold ${pctColor(s.change_pct)}`}>{fmtPct(s.change_pct)}</td>
        <td className="px-3 py-2 text-right font-mono text-gray-400 hidden sm:table-cell">{fmtNum(s.turnover)}</td>
        <td className="px-3 py-2 text-right font-mono text-gray-400 hidden md:table-cell">{fmtNum(s.volume_ratio)}</td>
        <td className="px-3 py-2 text-right font-mono text-gray-400 hidden lg:table-cell">{fmtNum(s.amplitude)}</td>
        <td className="px-3 py-2 text-right font-mono text-gray-300">{fmtNum(s.market_cap, 1)}</td>
        <td className="px-2 py-2 text-center">
          <button
            onClick={(e) => { e.stopPropagation(); loadAndToggle() }}
            className="text-gray-500 hover:text-blue-300 w-6 h-6 rounded-md hover:bg-gray-700/60 transition-colors"
            title="展开更多信息"
          >
            <span className={`inline-block text-[10px] transition-transform ${open ? 'rotate-180' : ''}`}>▼</span>
          </button>
        </td>
      </tr>
      {open && (
        <tr className="bg-gray-900/40" onClick={e => e.stopPropagation()}>
          <td colSpan={10} className="px-4 py-3 border-t border-gray-800/40">
            {loading && <div className="text-xs text-gray-500 py-2">加载详情中…</div>}
            {failed && <div className="text-xs text-red-400 py-2">详情加载失败，稍后重试</div>}
            {!loading && !failed && detail && (
              <div className="space-y-3 text-xs">
                {/* 行业 + 主营业务 */}
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-gray-500">行业</span>
                    <span className="px-2 py-0.5 rounded bg-blue-900/40 text-blue-300">{detail.industry || ind || '--'}</span>
                  </div>
                  <div className="text-gray-500 mt-2 mb-0.5">主营业务</div>
                  {biz?.business || biz?.products
                    ? <div className="text-gray-300 leading-relaxed">{biz?.business || biz?.products}</div>
                    : <div className="text-gray-600">暂无主营业务信息</div>}
                </div>
                {/* 最近表现 */}
                <div>
                  <div className="text-gray-500 mb-1">最近表现</div>
                  {r ? (
                    <>
                      {r.tags?.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mb-2">
                          {r.tags.map((t, k) => (
                            <span key={k} className="px-2 py-0.5 rounded bg-gray-800 text-gray-300">{t}</span>
                          ))}
                        </div>
                      )}
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1">
                        <Metric label="距MA5"  v={r.ma5_pct}  pct />
                        <Metric label="距MA20" v={r.ma20_pct} pct />
                        <Metric label="距MA60" v={r.ma60_pct} pct />
                        <KV label="MACD" v={r.macd_status || '--'} />
                        <KV label="RSI14" v={r.rsi14 == null ? '--' : r.rsi14.toFixed(0)} />
                        <KV label="量比" v={fmtNum(r.vol_ratio)} />
                        <KV label="连涨/跌" v={r.streak == null ? '--' : `${r.streak > 0 ? '+' : ''}${r.streak}天`} />
                      </div>
                    </>
                  ) : <div className="text-gray-600">暂无技术面数据</div>}
                </div>
                {/* 其他指标（原表格列移入） */}
                <div>
                  <div className="text-gray-500 mb-1">其他指标</div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1">
                    <KV label="流通市值" v={s.float_cap == null ? '--' : `${fmtNum(s.float_cap, 1)}亿`} />
                    <KV label="成交额" v={s.amount == null ? '--' : `${fmtNum(s.amount)}亿`} />
                    <KV label="市盈率PE" v={fmtNum(s.pe, 1)} />
                    <KV label="市净率PB" v={fmtNum(s.pb)} />
                  </div>
                </div>
                <div className="text-[11px] text-gray-600 pt-1">点击本行名称区域可跳转个股复盘 →</div>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

function Metric({ label, v, pct }: { label: string; v: number | null; pct?: boolean }) {
  const txt = v == null ? '--' : (pct ? fmtPct(v) : fmtNum(v))
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-gray-500">{label}</span>
      <span className={`font-mono ${pct ? pctColor(v) : 'text-gray-300'}`}>{txt}</span>
    </div>
  )
}

function KV({ label, v }: { label: string; v: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-gray-500">{label}</span>
      <span className="font-mono text-gray-300">{v}</span>
    </div>
  )
}

function RuleEditor({ fields, operators, patterns, rule, onClose, onSaved }: {
  fields: Field[]; operators: Operator[]; patterns: Pattern[]; rule: Rule | null
  onClose: () => void; onSaved: (id: string) => void
}) {
  const fmap: Record<string, Field> = {}
  fields.forEach(f => { fmap[f.key] = f })
  const defaultField = fields[0]?.key || 'change_pct'

  const [name, setName] = useState(rule?.name || '')
  const [conditions, setConditions] = useState<Condition[]>(rule?.conditions?.length ? rule.conditions : [])
  const [logic, setLogic] = useState(rule?.logic || 'AND')
  const [universe, setUniverse] = useState<Universe>(rule?.universe || {})
  const [sortField, setSortField] = useState(rule?.sort_field || 'change_pct')
  const [sortDir, setSortDir] = useState(rule?.sort_dir || 'desc')
  const [nlText, setNlText] = useState('')
  const [nlLoading, setNlLoading] = useState(false)
  const [nlMsg, setNlMsg] = useState('')
  const [imgLoading, setImgLoading] = useState(false)
  const [staged, setStaged] = useState<string[]>([])   // 待识别的截图（压缩后的 dataURL）
  const [dragOver, setDragOver] = useState(false)
  const [previewCount, setPreviewCount] = useState<number | null>(null)
  const [previewSample, setPreviewSample] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const debTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // ── 条件操作 ──
  const addCond = () => setConditions(cs => [...cs, { field: defaultField, op: 'gt', value: '' }])
  const updCond = (i: number, patch: Partial<Condition>) =>
    setConditions(cs => cs.map((c, idx) => idx === i ? { ...c, ...patch } : c))
  const delCond = (i: number) => setConditions(cs => cs.filter((_, idx) => idx !== i))

  // ── 实时预览（防抖）──
  useEffect(() => {
    if (debTimer.current) clearTimeout(debTimer.current)
    debTimer.current = setTimeout(async () => {
      try {
        const r = await fetch('/api/screen-rule/preview', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ conditions: cleanConditions(conditions), logic, universe, sort_field: sortField, sort_dir: sortDir, limit: 6 }),
        })
        const j = await r.json()
        setPreviewCount(j.total)
        setPreviewSample((j.stocks || []).map((s: StockRow) => s.name))
      } catch { setPreviewCount(null) }
    }, 450)
    return () => { if (debTimer.current) clearTimeout(debTimer.current) }
  }, [conditions, logic, universe, sortField, sortDir])

  // ── 回填 AI 解析结果（文字/截图共用）──
  const applyParsed = (j: { conditions?: Condition[]; logic?: string; universe?: Universe; name?: string }): number => {
    const conds: Condition[] = (j.conditions || []).map(c => ({ ...c, value: c.value as number, value2: c.value2 as number | undefined }))
    setConditions(conds)
    setLogic(j.logic || 'AND')
    setUniverse(j.universe || {})
    if (!name.trim() && j.name) setName(j.name)
    return conds.length
  }

  // ── AI 文字解析 ──
  const parseNl = async () => {
    if (nlText.trim().length < 2) return
    setNlLoading(true); setNlMsg('')
    try {
      const r = await fetch('/api/screen-rule/parse-nl', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: nlText.trim() }),
      })
      const j = await r.json()
      if (j.ok) {
        const n = applyParsed(j)
        setNlMsg(`✅ 已生成 ${n} 个条件，可继续微调`)
      } else {
        setNlMsg(`⚠️ 解析失败：${j.error || '请换种说法再试'}`)
      }
    } catch {
      setNlMsg('⚠️ 解析失败，请稍后再试')
    } finally {
      setNlLoading(false)
    }
  }

  // ── 截图识别：先在浏览器端压缩，再交给视觉 AI ──
  const compressImage = (file: File): Promise<string> => new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('read fail'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('decode fail'))
      img.onload = () => {
        const maxDim = 1600
        let w = img.width, h = img.height
        if (w > maxDim || h > maxDim) {
          const r = Math.min(maxDim / w, maxDim / h)
          w = Math.round(w * r); h = Math.round(h * r)
        }
        const canvas = document.createElement('canvas')
        canvas.width = w; canvas.height = h
        const ctx = canvas.getContext('2d')
        if (!ctx) { resolve(reader.result as string); return }
        ctx.drawImage(img, 0, 0, w, h)
        resolve(canvas.toDataURL('image/jpeg', 0.85))
      }
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  })

  const condKey = (c: Condition) => `${c.field}|${c.op}|${c.value}|${c.value2 ?? ''}`

  // 加入待识别队列（拖入/上传/粘贴都走这里）—— 只压缩+暂存，不立即识别。
  // 这样可以从微信一张张拖进来攒着，最后一次性识别。
  const addImages = async (files: File[]) => {
    const imgs = files.filter(f => f.type.startsWith('image/'))
    if (!imgs.length) return
    try {
      const urls = await Promise.all(imgs.map(compressImage))
      setStaged(prev => [...prev, ...urls])
      setNlMsg('')
    } catch { /* 忽略单张压缩失败 */ }
  }

  const removeStaged = (i: number) => setStaged(prev => prev.filter((_, idx) => idx !== i))
  const clearStaged = () => setStaged([])

  // 一次性识别队列里所有截图：并行调用视觉 AI，把各图条件「合并去重」到现有条件上
  const recognizeStaged = async () => {
    if (!staged.length || imgLoading) return
    setImgLoading(true)
    setNlMsg(staged.length > 1 ? `正在识别 ${staged.length} 张截图…` : '正在识别截图…')
    try {
      const results = await Promise.all(staged.map(async image => {
        try {
          const r = await fetch('/api/screen-rule/parse-image', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image }),
          })
          return await r.json()
        } catch { return { ok: false } }
      }))
      const okResults = results.filter(j => j && j.ok)
      const failed = results.length - okResults.length

      // 合并条件（追加到已有条件，去重）
      const merged: Condition[] = [...conditions]
      const seen = new Set(merged.map(condKey))
      let added = 0
      for (const j of okResults) {
        for (const c of (j.conditions || []) as Condition[]) {
          const cc: Condition = { ...c, value: c.value as number, value2: c.value2 as number | undefined }
          const k = condKey(cc)
          if (!seen.has(k)) { seen.add(k); merged.push(cc); added++ }
        }
      }
      setConditions(merged)

      // 排除项取并集
      const u: Universe = { ...universe }
      for (const j of okResults) {
        const uni = (j.universe || {}) as Universe
        ;(Object.keys(uni) as (keyof Universe)[]).forEach(k => { if (uni[k]) u[k] = true })
      }
      setUniverse(u)

      // 名字：当前为空时用第一张有名字的
      if (!name.trim()) {
        const nm = okResults.map(j => (j.name || '').trim()).find(Boolean)
        if (nm) setName(nm)
      }

      if (okResults.length === 0) {
        setNlMsg('⚠️ 没识别到可用条件，换更清晰的截图再试')   // 全失败：保留队列可重试
      } else {
        setNlMsg(`✅ 已从 ${okResults.length} 张截图识别 ${added} 个条件${failed ? `（${failed} 张失败）` : ''}，可继续微调`)
        setStaged([])   // 成功后清空队列
      }
    } catch {
      setNlMsg('⚠️ 识别失败，请稍后再试')
    } finally {
      setImgLoading(false)
    }
  }

  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const fs = e.target.files ? Array.from(e.target.files) : []
    if (fs.length) addImages(fs)
    e.target.value = ''   // 允许重复选同一批
  }

  // 粘贴截图（⌘/Ctrl+V）：用 ref 保证拿到最新的 addImages 闭包
  const addImagesRef = useRef(addImages)
  addImagesRef.current = addImages
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items
      if (!items) return
      const files: File[] = []
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith('image/')) {
          const f = items[i].getAsFile()
          if (f) files.push(f)
        }
      }
      if (files.length) { e.preventDefault(); addImagesRef.current(files) }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [])

  // ── 保存 ──
  const save = async () => {
    if (!name.trim()) { alert('请给规则起个名字'); return }
    setSaving(true)
    const payload = {
      name: name.trim(),
      conditions: cleanConditions(conditions),
      logic, universe, nl_source: nlText.trim(),
      sort_field: sortField, sort_dir: sortDir,
    }
    try {
      const url = rule ? `/api/screen-rule/rules/${rule.id}` : '/api/screen-rule/rules'
      const method = rule ? 'PUT' : 'POST'
      const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      const j = await r.json()
      const id = rule ? rule.id : j.id
      onSaved(id)
    } catch {
      alert('保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center bg-black/60 backdrop-blur-sm overflow-y-auto py-8 px-4" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-2xl shadow-2xl" onClick={e => e.stopPropagation()}>
        {/* 头 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h3 className="text-base font-bold text-white">{rule ? '编辑规则' : '新建规则'}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-white text-xl leading-none">✕</button>
        </div>

        <div className="p-5 space-y-5">
          {/* 规则名 */}
          <div>
            <label className="text-xs text-gray-500 mb-1 block">规则名称</label>
            <input
              value={name} onChange={e => setName(e.target.value)}
              placeholder="如：小市值高换手、低估值蓝筹…"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 outline-none focus:border-blue-500"
            />
          </div>

          {/* AI 生成：一句话 或 识别截图（支持拖入 / 粘贴）*/}
          <div
            onDragOver={e => { e.preventDefault(); if (!dragOver) setDragOver(true) }}
            onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false) }}
            onDrop={e => {
              e.preventDefault(); setDragOver(false)
              const fs = e.dataTransfer.files ? Array.from(e.dataTransfer.files) : []
              if (fs.length) addImages(fs)
            }}
            className={`relative bg-indigo-950/30 border rounded-xl p-3 space-y-2 transition-colors ${
              dragOver ? 'border-indigo-400 ring-2 ring-indigo-400/40' : 'border-indigo-800/40'
            }`}
          >
            <label className="text-xs text-indigo-300 flex items-center gap-1">🪄 让 AI 帮你生成条件</label>
            <div className="flex gap-2">
              <input
                value={nlText} onChange={e => setNlText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') parseNl() }}
                placeholder="如：小市值、今天涨3~8个点、换手大于10%，排除ST"
                className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 outline-none focus:border-indigo-500"
              />
              <button
                onClick={parseNl} disabled={nlLoading || nlText.trim().length < 2}
                className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm px-3 py-2 rounded-lg whitespace-nowrap transition-colors"
              >{nlLoading ? '解析中…' : 'AI 解析'}</button>
            </div>

            {/* 截图：拖入/上传/粘贴先攒进队列，最后一次性识别 */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => fileInputRef.current?.click()} disabled={imgLoading}
                className="bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed text-indigo-200 text-sm px-3 py-1.5 rounded-lg border border-indigo-800/50 whitespace-nowrap transition-colors"
              >📷 添加截图</button>
              <span className="text-[11px] text-gray-500">从微信一张张拖进来攒着 · 也可点击上传 / ⌘·Ctrl+V 粘贴</span>
            </div>
            <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={onPickFile} className="hidden" />

            {/* 待识别队列 */}
            {staged.length > 0 && (
              <div className="bg-gray-900/60 border border-indigo-900/40 rounded-lg p-2 space-y-2">
                <div className="flex flex-wrap gap-2">
                  {staged.map((src, i) => (
                    <div key={i} className="relative group">
                      <img src={src} alt={`截图${i + 1}`} className="h-14 w-14 object-cover rounded border border-indigo-800/50" />
                      <button
                        onClick={() => removeStaged(i)} disabled={imgLoading}
                        className="absolute -top-1.5 -right-1.5 bg-gray-950 border border-gray-600 text-gray-300 hover:text-red-400 rounded-full w-4 h-4 text-[10px] leading-none flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                        title="移除"
                      >✕</button>
                    </div>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={recognizeStaged} disabled={imgLoading}
                    className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors"
                  >{imgLoading ? '识别中…' : `🔍 识别这 ${staged.length} 张截图`}</button>
                  <button
                    onClick={clearStaged} disabled={imgLoading}
                    className="text-[11px] text-gray-500 hover:text-gray-300 disabled:opacity-50"
                  >清空</button>
                </div>
              </div>
            )}

            {nlMsg && <p className="text-xs text-gray-400">{nlMsg}</p>}

            {dragOver && (
              <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-indigo-950/80 border-2 border-dashed border-indigo-400 pointer-events-none">
                <p className="text-sm text-indigo-200 font-medium">📷 松开加入队列（攒齐后一起识别）</p>
              </div>
            )}
          </div>

          {/* 条件搭建 */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs text-gray-500">筛选条件</label>
              <div className="flex gap-1 bg-gray-800 rounded-lg p-0.5">
                {([['AND', '同时满足'], ['OR', '满足任一']] as const).map(([k, lbl]) => (
                  <button key={k} onClick={() => setLogic(k)}
                    className={`text-xs px-2.5 py-1 rounded-md transition-colors ${logic === k ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                  >{lbl}</button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              {conditions.map((c, i) => {
                const f = fmap[c.field]
                return (
                  <div key={i} className="flex items-center gap-2">
                    <select value={c.field} onChange={e => updCond(i, { field: e.target.value })}
                      className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-200 outline-none focus:border-blue-500">
                      {fields.map(fd => <option key={fd.key} value={fd.key}>{fd.label}</option>)}
                    </select>
                    <select value={c.op} onChange={e => updCond(i, { op: e.target.value })}
                      className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-200 outline-none focus:border-blue-500">
                      {operators.map(op => <option key={op.key} value={op.key}>{op.label}</option>)}
                    </select>
                    <input type="number" value={c.value} onChange={e => updCond(i, { value: e.target.value === '' ? '' : Number(e.target.value) })}
                      className="w-20 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-200 outline-none focus:border-blue-500" />
                    {c.op === 'between' && (
                      <>
                        <span className="text-gray-500 text-xs">~</span>
                        <input type="number" value={c.value2 ?? ''} onChange={e => updCond(i, { value2: e.target.value === '' ? '' : Number(e.target.value) })}
                          className="w-20 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-200 outline-none focus:border-blue-500" />
                      </>
                    )}
                    <span className="text-xs text-gray-500 w-8">{f?.unit}</span>
                    <button onClick={() => delCond(i)} className="text-gray-600 hover:text-red-400 text-sm ml-auto px-1">✕</button>
                  </div>
                )
              })}
            </div>

            <button onClick={addCond} className="mt-2 text-xs text-blue-400 hover:text-blue-300">+ 添加条件</button>
          </div>

          {/* 排除项 */}
          <div>
            <label className="text-xs text-gray-500 mb-1.5 block">股票池排除</label>
            <div className="flex flex-wrap gap-2">
              {UNIVERSE_LABELS.map(u => (
                <button key={u.key} onClick={() => setUniverse(uni => ({ ...uni, [u.key]: !uni[u.key] }))}
                  className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                    universe[u.key] ? 'bg-blue-600/20 border-blue-500/60 text-blue-300' : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-white'
                  }`}
                >{universe[u.key] ? '✓ ' : ''}{u.label}</button>
              ))}
            </div>
          </div>

          {/* 形态条件（多日趋势，需历史日线） */}
          <div>
            <label className="text-xs text-gray-500 mb-1.5 block">形态条件 <span className="text-gray-600">（多日量价趋势，多选则同时满足；对筛选结果二次过滤）</span></label>
            <div className="flex flex-wrap gap-2">
              {patterns.map(p => (
                <button key={p.key} title={p.hint} onClick={() => setUniverse(uni => ({ ...uni, [p.key]: !uni[p.key] }))}
                  className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                    universe[p.key] ? 'bg-amber-600/20 border-amber-500/60 text-amber-300' : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-white'
                  }`}
                >{universe[p.key] ? '✓ ' : ''}📈 {p.label}</button>
              ))}
            </div>
            {patterns.some(p => universe[p.key]) && (
              <div className="mt-1.5 space-y-0.5">
                {patterns.filter(p => universe[p.key]).map(p => (
                  <p key={p.key} className="text-[11px] text-amber-200/70 leading-relaxed">· {p.label}：{p.hint}</p>
                ))}
                <p className="text-[11px] text-amber-200/50 leading-relaxed">形态条件需逐只拉取历史日线，仅对数值筛选后的候选股二次过滤，首次运行稍慢（约 10–30 秒），之后当日缓存秒开。建议先用数值条件收敛范围，再叠加形态。</p>
              </div>
            )}
          </div>

          {/* 排序 */}
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500">结果排序</label>
            <select value={sortField} onChange={e => setSortField(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-200 outline-none focus:border-blue-500">
              {fields.map(fd => <option key={fd.key} value={fd.key}>{fd.label}</option>)}
            </select>
            <div className="flex gap-1 bg-gray-800 rounded-lg p-0.5">
              {([['desc', '降序'], ['asc', '升序']] as const).map(([k, lbl]) => (
                <button key={k} onClick={() => setSortDir(k)}
                  className={`text-xs px-2.5 py-1 rounded-md transition-colors ${sortDir === k ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                >{lbl}</button>
              ))}
            </div>
          </div>

          {/* 实时预览 */}
          <div className="bg-gray-800/50 border border-gray-700/60 rounded-xl px-3 py-2.5">
            <div className="flex items-center gap-2 text-sm">
              <span className="text-gray-400">预计筛选出</span>
              <span className="text-blue-400 font-bold font-mono text-base">{previewCount === null ? '…' : previewCount}</span>
              <span className="text-gray-400">只</span>
            </div>
            {previewSample.length > 0 && (
              <div className="text-xs text-gray-500 mt-1 truncate">例：{previewSample.join('、')}…</div>
            )}
          </div>
        </div>

        {/* 底部按钮 */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-800">
          <button onClick={onClose} className="text-sm text-gray-400 hover:text-white px-4 py-2 rounded-lg transition-colors">取消</button>
          <button onClick={save} disabled={saving}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-lg transition-colors">
            {saving ? '保存中…' : (rule ? '保存修改' : '创建规则')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// 回测弹窗：参数选择 + 进度轮询 + 净值曲线 + 统计
// ══════════════════════════════════════════════════════════════════════════════
type BtStats = {
  total_return_pct: number; bench_return_pct: number; excess_pct: number
  max_drawdown_pct: number; win_rate: number; sharpe: number
  rebalance_count: number; avg_picks: number
  flat_days?: number; exposure_pct?: number
}
type BtNavPoint = { date: string; strategy: number; benchmark: number | null }
type BtRebalance = { date: string; sell: string; picks: string[]; ret: number; n: number }
type BtResult = {
  ok: boolean; rule_name: string; window_days: number; hold_days: number
  top_k: number; benchmark: string; pool_label: string; pool_size: number
  skipped_conditions?: string[]
  stats: BtStats; nav: BtNavPoint[]; rebalances: BtRebalance[]; generated_at: string
}
type BtStatus = {
  state: 'idle' | 'running' | 'done' | 'error'
  stage?: string; progress?: number; pool_size?: number; pool_label?: string
  result?: BtResult; error?: string; elapsed?: number; params?: any
}

function BacktestModal({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const [window_days, setWindow] = useState(120)
  const [hold_days,   setHold]   = useState(5)
  const [top_k,       setTopK]   = useState(10)
  const [benchmark,   setBench]  = useState('上证综指')
  const [status, setStatus] = useState<BtStatus>({ state: 'idle' })
  const pollRef = useRef<number | null>(null)

  // 进入弹窗时拉一次现有状态（可能上次跑过了）
  useEffect(() => {
    fetch(`/api/screen-rule/rules/${rule.id}/backtest/status`)
      .then(r => r.json()).then((s: BtStatus) => setStatus(s)).catch(() => {})
    return () => { if (pollRef.current) window.clearInterval(pollRef.current) }
  }, [rule.id])

  // 跑起来后轮询
  useEffect(() => {
    if (status.state !== 'running') {
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null }
      return
    }
    if (pollRef.current) return
    pollRef.current = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/screen-rule/rules/${rule.id}/backtest/status`)
        const s: BtStatus = await r.json()
        setStatus(s)
      } catch { /* ignore */ }
    }, 1500)
    return () => { if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null } }
  }, [status.state, rule.id])

  const start = async () => {
    setStatus({ state: 'running', stage: '提交回测任务', progress: 0 })
    try {
      const u = `/api/screen-rule/rules/${rule.id}/backtest/start?window_days=${window_days}&hold_days=${hold_days}&top_k=${top_k}&benchmark=${encodeURIComponent(benchmark)}`
      await fetch(u, { method: 'POST' })
      // 立即拉一次状态
      const r = await fetch(`/api/screen-rule/rules/${rule.id}/backtest/status`)
      setStatus(await r.json())
    } catch {
      setStatus({ state: 'error', error: '启动失败' })
    }
  }

  const r = status.result
  const stats = r?.stats

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* 头部 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800">
          <div>
            <h3 className="text-base font-bold text-white">📊 回测 · <span className="text-emerald-300">{rule.name}</span></h3>
            <p className="text-[11px] text-gray-500 mt-0.5">每 {hold_days} 个交易日重平衡 · 等权持仓 top {top_k} · vs {benchmark}</p>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white text-xl leading-none">✕</button>
        </div>

        {/* 参数行 */}
        <div className="flex flex-wrap items-center gap-3 px-5 py-3 border-b border-gray-800 text-xs">
          <label className="flex items-center gap-1.5 text-gray-400">窗口
            <select value={window_days} onChange={e => setWindow(Number(e.target.value))}
              disabled={status.state === 'running'}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200">
              <option value={60}>60 个交易日</option>
              <option value={120}>120 个交易日</option>
              <option value={240}>240 个交易日（≈1 年）</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-gray-400">持仓
            <select value={hold_days} onChange={e => setHold(Number(e.target.value))}
              disabled={status.state === 'running'}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200">
              <option value={3}>3 日</option>
              <option value={5}>5 日</option>
              <option value={10}>10 日</option>
              <option value={20}>20 日</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-gray-400">持仓数
            <select value={top_k} onChange={e => setTopK(Number(e.target.value))}
              disabled={status.state === 'running'}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200">
              <option value={5}>5 只</option>
              <option value={10}>10 只</option>
              <option value={20}>20 只</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-gray-400">基准
            <select value={benchmark} onChange={e => setBench(e.target.value)}
              disabled={status.state === 'running'}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200">
              <option>上证综指</option>
              <option>沪深300</option>
              <option>中证500</option>
            </select>
          </label>
          <button onClick={start} disabled={status.state === 'running'}
            className="ml-auto bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-medium px-4 py-1.5 rounded-lg">
            {status.state === 'running' ? '回测中…' : (r ? '重新回测' : '开始回测')}
          </button>
        </div>

        {/* 进度 / 结果 */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {status.state === 'idle' && !r && (
            <div className="text-center text-gray-500 text-sm py-12">
              点上方「开始回测」启动一次真回测<br/>
              <span className="text-[11px] text-gray-600">候选池：{rule.kind === 'theme' ? `题材「${rule.theme}」成分股` : '沪深300 成分股'}（首跑较慢，当日缓存）</span>
            </div>
          )}
          {status.state === 'running' && (
            <div className="py-8">
              <div className="flex items-center text-sm text-gray-300 mb-2">
                <svg className="animate-spin h-4 w-4 mr-2" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                {status.stage || '回测中…'}
              </div>
              <div className="w-full bg-gray-800 rounded-full h-2 overflow-hidden">
                <div className="bg-emerald-500 h-2 transition-all" style={{ width: `${Math.max(2, status.progress || 0)}%` }} />
              </div>
              {status.pool_size != null && (
                <p className="text-[11px] text-gray-500 mt-2">候选池：{status.pool_label}（{status.pool_size} 只）· 首跑约 30s ~ 3 分钟，当日缓存后秒回</p>
              )}
            </div>
          )}
          {status.state === 'error' && (
            <div className="text-center text-red-300 text-sm py-12">
              回测出错：{status.error}<br/>
              <button onClick={start} className="mt-3 text-xs border border-red-800/60 rounded-lg px-3 py-1 hover:bg-red-900/30">↻ 重试</button>
            </div>
          )}
          {r && stats && (
            <div className="space-y-4">
              {r.skipped_conditions && r.skipped_conditions.length > 0 && (
                <div className="text-[11px] bg-amber-950/30 border border-amber-800/40 text-amber-200/90 rounded-lg px-3 py-2">
                  注：历史日K不含 {r.skipped_conditions.join('、')}，这些条件在回测中未参与判定（其他数值/形态条件正常生效）。
                </div>
              )}
              {/* 统计卡片 */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <StatCard label="策略累计收益" v={`${stats.total_return_pct.toFixed(2)}%`} color={stats.total_return_pct >= 0 ? 'text-red-400' : 'text-green-400'} />
                <StatCard label={`${r.benchmark}收益`} v={`${stats.bench_return_pct.toFixed(2)}%`} color={stats.bench_return_pct >= 0 ? 'text-red-400' : 'text-green-400'} />
                <StatCard label="超额收益" v={`${stats.excess_pct >= 0 ? '+' : ''}${stats.excess_pct.toFixed(2)}%`} color={stats.excess_pct >= 0 ? 'text-red-400' : 'text-green-400'} />
                <StatCard label="最大回撤" v={`${stats.max_drawdown_pct.toFixed(2)}%`} color="text-amber-400" />
                <StatCard label="胜率" v={`${(stats.win_rate * 100).toFixed(0)}%`} color="text-blue-300" />
                <StatCard label="夏普" v={stats.sharpe.toFixed(2)} color="text-blue-300" />
                <StatCard label="重平衡次数" v={String(stats.rebalance_count)} color="text-gray-300" />
                <StatCard label={`平均持仓 · 仓位${stats.exposure_pct != null ? ' '+stats.exposure_pct.toFixed(0)+'%' : ''}`} v={stats.avg_picks.toFixed(1)} color={(stats.exposure_pct ?? 100) < 60 ? 'text-amber-400' : 'text-gray-300'} />
              </div>

              {/* 净值曲线 */}
              <BacktestChart nav={r.nav} bench={r.benchmark} />

              {/* 每期持仓 */}
              <details className="rounded-lg border border-gray-800">
                <summary className="px-3 py-2 text-xs text-gray-400 cursor-pointer hover:text-gray-200">
                  各期重平衡明细（{r.rebalances.length} 次） · 展开查看
                </summary>
                <div className="max-h-64 overflow-y-auto px-3 py-2 text-xs">
                  <table className="w-full">
                    <thead className="text-gray-600 sticky top-0 bg-gray-900">
                      <tr><th className="text-left py-1">日期</th><th className="text-left">卖出</th><th className="text-right">持仓数</th><th className="text-right">期内收益</th><th className="text-left pl-3">持仓</th></tr>
                    </thead>
                    <tbody>
                      {r.rebalances.map((rb, i) => (
                        <tr key={i} className="border-t border-gray-800/40">
                          <td className="py-1 text-gray-400">{rb.date}</td>
                          <td className="text-gray-500">{rb.sell}</td>
                          <td className="text-right text-gray-400 font-mono">{rb.n}</td>
                          <td className={`text-right font-mono ${rb.ret >= 0 ? 'text-red-400' : 'text-green-400'}`}>{(rb.ret * 100).toFixed(2)}%</td>
                          <td className="pl-3 text-gray-500 truncate max-w-[16rem]" title={rb.picks.join(' ')}>{rb.picks.slice(0, 6).join(' ')}{rb.picks.length > 6 ? ` …+${rb.picks.length - 6}` : ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>

              <p className="text-[11px] text-gray-600 text-center">
                候选池：{r.pool_label}（{r.pool_size} 只）· 首跑耗时 {status.elapsed?.toFixed?.(1) || '-'}s · {r.generated_at} · 仅供研究参考，不构成投资建议
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, v, color }: { label: string; v: string; color: string }) {
  return (
    <div className="bg-gray-800/50 border border-gray-800 rounded-lg px-3 py-2">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className={`text-base font-mono font-semibold ${color}`}>{v}</div>
    </div>
  )
}

function BacktestChart({ nav, bench }: { nav: BtNavPoint[]; bench: string }) {
  // 净值统一以 1.0 起点。横轴用每隔 N 显示日期。
  const data = nav.map(p => ({
    date: p.date,
    strategy: p.strategy,
    benchmark: p.benchmark,
  }))
  return (
    <div className="h-72 bg-gray-950/40 rounded-lg border border-gray-800 p-2">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 15, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="date" stroke="#6b7280" tick={{ fontSize: 10 }} interval={Math.max(1, Math.floor(data.length / 8))} />
          <YAxis stroke="#6b7280" tick={{ fontSize: 10 }} domain={['auto', 'auto']} tickFormatter={(v: number) => v.toFixed(2)} />
          <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
            formatter={(value, name) => [Number(value ?? 0).toFixed(4), name === 'strategy' ? '策略' : bench] as [string, string]} />
          <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => v === 'strategy' ? '策略' : bench} />
          <Line type="monotone" dataKey="strategy" stroke="#10b981" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="benchmark" stroke="#9ca3af" strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
