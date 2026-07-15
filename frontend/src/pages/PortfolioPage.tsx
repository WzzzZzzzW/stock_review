/**
 * 持仓管理页
 * - 持仓总览（总市值/总盈亏/今日盈亏）
 * - 持仓列表（每支：成本/现价/盈亏/止损/目标/持有天数）
 * - 候选池（研究中的标的）
 * - 新增/编辑持仓表单
 */
import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import StockSearch from '../components/StockSearch'
import DividendAdjustPanel from '../components/DividendAdjustPanel'

// ── 市场时间工具 ──────────────────────────────────────────────────────────────
function getMarketStatus(): { open: boolean; label: string; color: string; interval: number | false } {
  const now = new Date()
  const day  = now.getDay()                       // 0=周日 6=周六
  const hhmm = now.getHours() * 100 + now.getMinutes()

  const isWeekday  = day >= 1 && day <= 5
  const isMorning  = hhmm >= 930  && hhmm < 1130  // 9:30-11:30
  const isAfternoon= hhmm >= 1300 && hhmm < 1500  // 13:00-15:00
  const isOpen     = isWeekday && (isMorning || isAfternoon)

  if (isOpen) {
    return { open: true,  label: '交易中',  color: 'text-green-400', interval: 15_000  }  // 15秒
  }
  // 盘前（工作日早上9点前）or 集合竞价（9:15-9:30）
  if (isWeekday && hhmm >= 900 && hhmm < 930) {
    return { open: false, label: '集合竞价', color: 'text-yellow-400', interval: 30_000 }  // 30秒
  }
  return { open: false, label: '已收盘',   color: 'text-gray-500',  interval: false }    // 不自动刷新
}

// ── Types ─────────────────────────────────────────────────────────────────────
interface Position {
  symbol: string; name: string
  buy_date: string; buy_price: number; quantity: number
  stop_loss: number; target_price: number; notes: string
  current_price: number; pct_change: number
  cost_value: number; current_value: number
  pnl_amount: number; pnl_pct: number; today_pnl: number
  holding_days: number
  at_stop_loss: boolean; near_stop_loss: boolean; at_target: boolean
  stop_progress: number; target_progress: number
}
interface Summary {
  total_cost: number; total_value: number
  total_pnl_amount: number; total_pnl_pct: number
  today_pnl: number; position_count: number
}
interface Alert { symbol: string; name: string; type: string; message: string }
interface PortfolioResp {
  positions: Position[]; summary: Summary
  alerts: Alert[]; updated_at: string
}
interface Candidate {
  symbol: string; name: string; reason: string
  target_entry: number; added_at: string
  current_price: number; pct_change: number
}
interface CandidateResp { candidates: Candidate[]; updated_at: string }

interface TradeAI {
  score: number; grade: string; summary: string
  pros: string[]; cons: string[]; advice: string
}
interface Trade {
  id: string; symbol: string; name: string
  action: 'buy' | 'sell'; quantity: number; price: number
  reason: string; trade_date: string; at: string
  ai_status: 'processing' | 'done' | 'error'
  ai: TradeAI | null; ai_error?: string
  position_synced: boolean
}
interface TradesResp {
  trades: Trade[]; date: string
  summary: { count: number; buy_amount: number; sell_amount: number; avg_score: number | null }
}

type SellDecision = '清仓' | '减仓' | '持有' | '加仓'
interface SellData {
  decision: SellDecision; urgency: number; summary: string
  reduce_pct: number; sell_price: number | null; stop_price: number | null
  reasons: string[]; matched_rules: string[]; advice: string
}
interface SellGuidance {
  status: 'processing' | 'done' | 'error'
  at: string; name?: string; error?: string; data?: SellData
}
type GuidanceMap = Record<string, SellGuidance>
interface GuidanceResp { guidance: GuidanceMap }

// ── 颜色工具 ──────────────────────────────────────────────────────────────────
function pctColor(p: number) {
  if (p > 0) return 'text-red-400'
  if (p < 0) return 'text-emerald-400'
  return 'text-gray-400'
}
function fmt(n: number, prefix = '¥') {
  const abs = Math.abs(n)
  if (abs >= 1e8) return `${prefix}${(n / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${prefix}${(n / 1e4).toFixed(2)}万`
  return `${prefix}${n.toFixed(2)}`
}

// ── 空状态 ────────────────────────────────────────────────────────────────────
function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="text-center py-16 space-y-4">
      <div className="text-5xl">📂</div>
      <p className="text-gray-400 text-sm font-medium">还没有持仓记录</p>
      <p className="text-gray-600 text-xs">添加持仓后，AI 每天会自动生成盘前计划和盘后复盘</p>
      <button
        onClick={onAdd}
        className="mt-2 px-5 py-2 bg-blue-600/30 hover:bg-blue-600/50 text-blue-400 border border-blue-700/50 rounded-xl text-sm transition-colors"
      >
        + 添加第一笔持仓
      </button>
    </div>
  )
}

// ── 卖点诊断展示 ──────────────────────────────────────────────────────────────
const DECISION_STYLE: Record<SellDecision, { chip: string; banner: string; emoji: string }> = {
  清仓: { chip: 'bg-rose-600 text-white',       banner: 'bg-rose-900/50 text-rose-200 border-rose-700/50',   emoji: '🚨' },
  减仓: { chip: 'bg-amber-500 text-gray-950',   banner: 'bg-amber-900/40 text-amber-200 border-amber-700/50', emoji: '✂️' },
  持有: { chip: 'bg-emerald-600 text-white',    banner: 'bg-emerald-900/30 text-emerald-200 border-emerald-800/40', emoji: '✊' },
  加仓: { chip: 'bg-sky-600 text-white',        banner: 'bg-sky-900/30 text-sky-200 border-sky-800/40',       emoji: '➕' },
}

/** 折叠态顶部的决策横幅（一眼看到该不该卖） */
function DecisionBanner({ g }: { g: SellGuidance }) {
  if (g.status === 'processing') {
    return (
      <div className="bg-gray-800/60 px-4 py-1.5 flex items-center gap-2">
        <div className="w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"/>
        <span className="text-gray-400 text-xs">AI 正在诊断卖点…</span>
      </div>
    )
  }
  if (g.status === 'error') {
    return <div className="bg-rose-950/40 px-4 py-1.5"><span className="text-rose-400 text-xs">卖点诊断失败{g.error ? `：${g.error}` : ''}</span></div>
  }
  if (!g.data) return null
  const st = DECISION_STYLE[g.data.decision]
  return (
    <div className={`px-4 py-1.5 flex items-center gap-2 border-b ${st.banner}`}>
      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${st.chip}`}>{st.emoji} {g.data.decision}</span>
      <span className="text-xs truncate flex-1">{g.data.summary}</span>
      <span className="text-[10px] opacity-70 shrink-0">紧迫度 {g.data.urgency}</span>
    </div>
  )
}

/** 展开态的完整诊断 */
function SellDiagnosisDetail({ g, onRediagnose }: { g: SellGuidance; onRediagnose: () => void }) {
  if (g.status === 'processing') {
    return <p className="text-xs text-gray-500 flex items-center gap-2"><span className="w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"/>AI 正在诊断卖点…</p>
  }
  if (g.status === 'error' || !g.data) {
    return (
      <div className="flex items-center justify-between text-xs text-rose-400">
        <span>诊断失败{g.error ? `：${g.error}` : ''}</span>
        <button onClick={onRediagnose} className="text-blue-400 hover:text-blue-300">重试</button>
      </div>
    )
  }
  const d = g.data
  const st = DECISION_STYLE[d.decision]
  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded-xl p-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="text-[10px] text-gray-500 font-semibold uppercase tracking-widest">🩺 卖点诊断</p>
        <button onClick={onRediagnose} className="text-[10px] text-gray-600 hover:text-gray-400">重新诊断</button>
      </div>

      <div className="flex items-center gap-2.5">
        <span className={`text-sm font-bold px-3 py-1.5 rounded-xl ${st.chip}`}>{st.emoji} {d.decision}</span>
        <p className="text-sm text-gray-200 font-medium flex-1">{d.summary}</p>
      </div>

      {/* 价位/比例 */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-gray-900/60 rounded-lg py-1.5">
          <p className="text-[9px] text-gray-600">建议止损</p>
          <p className="text-xs font-mono text-rose-300 mt-0.5">{d.stop_price ? `¥${d.stop_price}` : '—'}</p>
        </div>
        <div className="bg-gray-900/60 rounded-lg py-1.5">
          <p className="text-[9px] text-gray-600">{d.decision === '加仓' ? '破位价' : '止盈/卖出'}</p>
          <p className="text-xs font-mono text-amber-300 mt-0.5">{d.sell_price ? `¥${d.sell_price}` : '—'}</p>
        </div>
        <div className="bg-gray-900/60 rounded-lg py-1.5">
          <p className="text-[9px] text-gray-600">建议减仓</p>
          <p className="text-xs font-mono text-gray-200 mt-0.5">{d.reduce_pct > 0 ? `${d.reduce_pct}%` : '—'}</p>
        </div>
      </div>

      {d.reasons.length > 0 && (
        <div className="space-y-0.5">
          {d.reasons.map((r, i) => <p key={i} className="text-[11px] text-gray-400 leading-relaxed">· {r}</p>)}
        </div>
      )}

      {d.matched_rules.length > 0 && (
        <div className="bg-purple-950/20 border border-purple-900/40 rounded-lg px-2.5 py-1.5 space-y-0.5">
          <p className="text-[10px] text-purple-400 font-semibold">🧠 命中你的脑库规则</p>
          {d.matched_rules.map((r, i) => <p key={i} className="text-[11px] text-purple-300/90 leading-relaxed">「{r}」</p>)}
        </div>
      )}

      {d.advice && (
        <p className="text-[11px] text-blue-300/90 bg-blue-950/30 border border-blue-900/40 rounded-lg px-2.5 py-1.5 leading-relaxed">🎯 {d.advice}</p>
      )}

      <p className="text-[9px] text-gray-700 text-right">诊断于 {g.at.slice(5, 16).replace('T', ' ')} · 仅供参考，不构成投资建议</p>
    </div>
  )
}

// ── 持仓卡片 ──────────────────────────────────────────────────────────────────
function PositionCard({
  p, onEdit, onDelete, guidance, onDiagnose,
}: {
  p: Position; onEdit: (p: Position) => void; onDelete: (sym: string) => void
  guidance?: SellGuidance; onDiagnose: (sym: string) => void
}) {
  const [open, setOpen] = useState(false)

  const alertBorder = p.at_stop_loss  ? 'border-red-600/70 bg-red-950/20'
                    : p.near_stop_loss ? 'border-orange-700/50 bg-orange-950/10'
                    : p.at_target      ? 'border-amber-600/60 bg-amber-950/10'
                    : 'border-gray-800/60 bg-gray-900/60'

  return (
    <div className={`rounded-2xl border overflow-hidden transition-all ${alertBorder}`}>
      {/* 卖点诊断横幅 */}
      {guidance && <DecisionBanner g={guidance} />}
      {/* 警告横幅 */}
      {p.at_stop_loss && (
        <div className="bg-red-900/60 px-4 py-1.5 flex items-center gap-2">
          <span className="text-red-300 text-xs font-bold animate-pulse">⚠️ 已触及止损线，请执行止损纪律</span>
        </div>
      )}
      {p.near_stop_loss && !p.at_stop_loss && (
        <div className="bg-orange-900/40 px-4 py-1.5">
          <span className="text-orange-300 text-xs">🔶 接近止损线（{((1 - p.stop_progress) * 100).toFixed(1)}% 空间），密切关注</span>
        </div>
      )}
      {p.at_target && (
        <div className="bg-amber-900/40 px-4 py-1.5">
          <span className="text-amber-300 text-xs">🎯 已达目标价，考虑减仓/止盈</span>
        </div>
      )}

      {/* 主体 */}
      <button className="w-full text-left px-4 py-4" onClick={() => setOpen(o => !o)}>
        <div className="flex items-start justify-between gap-3">
          {/* 左：股票信息 */}
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-base font-bold text-white">{p.name}</span>
              <span className="text-xs text-gray-500 font-mono">{p.symbol}</span>
              <span className="text-[10px] text-gray-600 border border-gray-700 px-1.5 py-0.5 rounded">
                持仓{p.holding_days}天
              </span>
            </div>
            {/* 今日涨跌 */}
            <div className="flex items-center gap-3 mt-1">
              <span className="text-sm font-mono font-semibold text-white">
                ¥{p.current_price.toFixed(2)}
              </span>
              <span className={`text-xs font-mono ${pctColor(p.pct_change)}`}>
                {p.pct_change > 0 ? '+' : ''}{p.pct_change.toFixed(2)}%
              </span>
              <span className={`text-xs ${pctColor(p.today_pnl)}`}>
                今日 {p.today_pnl > 0 ? '+' : ''}{fmt(p.today_pnl, '')}
              </span>
            </div>
          </div>

          {/* 右：总盈亏 */}
          <div className="text-right shrink-0">
            <p className={`text-lg font-bold font-mono ${pctColor(p.pnl_pct)}`}>
              {p.pnl_pct > 0 ? '+' : ''}{p.pnl_pct.toFixed(2)}%
            </p>
            <p className={`text-xs font-mono ${pctColor(p.pnl_amount)}`}>
              {p.pnl_amount > 0 ? '+' : ''}{fmt(p.pnl_amount, '')}
            </p>
          </div>
        </div>

        {/* 进度条：止损 ← 现价 → 目标 */}
        {(p.stop_loss > 0 || p.target_price > 0) && (
          <div className="mt-3 space-y-1">
            {p.stop_loss > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-gray-600 w-8">止损</span>
                <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${p.at_stop_loss ? 'bg-red-500' : p.near_stop_loss ? 'bg-orange-500' : 'bg-gray-600'}`}
                    style={{ width: `${p.stop_progress * 100}%` }}
                  />
                </div>
                <span className="text-[9px] text-gray-600 w-12 text-right">¥{p.stop_loss.toFixed(2)}</span>
              </div>
            )}
            {p.target_price > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-gray-600 w-8">目标</span>
                <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${p.at_target ? 'bg-amber-400' : 'bg-blue-600'}`}
                    style={{ width: `${p.target_progress * 100}%` }}
                  />
                </div>
                <span className="text-[9px] text-gray-600 w-12 text-right">¥{p.target_price.toFixed(2)}</span>
              </div>
            )}
          </div>
        )}
      </button>

      {/* 展开详情 */}
      {open && (
        <div className="border-t border-gray-800/60 px-4 py-3 space-y-3">
          <div className="grid grid-cols-3 gap-3 text-xs">
            <div className="bg-gray-800/40 rounded-xl p-3 space-y-1">
              <p className="text-gray-600">成本价</p>
              <p className="text-white font-mono font-semibold">¥{p.buy_price.toFixed(2)}</p>
            </div>
            <div className="bg-gray-800/40 rounded-xl p-3 space-y-1">
              <p className="text-gray-600">持仓数量</p>
              <p className="text-white font-mono font-semibold">{p.quantity.toLocaleString()}股</p>
            </div>
            <div className="bg-gray-800/40 rounded-xl p-3 space-y-1">
              <p className="text-gray-600">买入日期</p>
              <p className="text-white font-mono font-semibold">{p.buy_date}</p>
            </div>
            <div className="bg-gray-800/40 rounded-xl p-3 space-y-1">
              <p className="text-gray-600">持仓成本</p>
              <p className="text-white font-mono font-semibold">{fmt(p.cost_value)}</p>
            </div>
            <div className="bg-gray-800/40 rounded-xl p-3 space-y-1">
              <p className="text-gray-600">当前市值</p>
              <p className="text-white font-mono font-semibold">{fmt(p.current_value)}</p>
            </div>
            <div className="bg-gray-800/40 rounded-xl p-3 space-y-1">
              <p className="text-gray-600">总盈亏</p>
              <p className={`font-mono font-semibold ${pctColor(p.pnl_amount)}`}>
                {p.pnl_amount > 0 ? '+' : ''}{fmt(p.pnl_amount)}
              </p>
            </div>
          </div>

          {p.notes && (
            <div className="bg-blue-950/20 border border-blue-900/30 rounded-xl px-3 py-2">
              <p className="text-[10px] text-gray-500 mb-1">📝 备注</p>
              <p className="text-xs text-gray-400">{p.notes}</p>
            </div>
          )}

          {/* 卖点诊断 */}
          {guidance ? (
            <SellDiagnosisDetail g={guidance} onRediagnose={() => onDiagnose(p.symbol)} />
          ) : (
            <button
              onClick={() => onDiagnose(p.symbol)}
              className="w-full text-xs py-2 bg-purple-950/30 hover:bg-purple-900/40 text-purple-300 border border-purple-900/40 rounded-xl transition-colors"
            >🩺 AI 卖点诊断（该卖还是该拿？）</button>
          )}

          <div className="flex gap-2 pt-1">
            <button
              onClick={() => onEdit(p)}
              className="flex-1 text-xs py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-xl transition-colors"
            >编辑</button>
            <button
              onClick={() => onDelete(p.symbol)}
              className="flex-1 text-xs py-2 bg-red-950/30 hover:bg-red-900/40 text-red-400 border border-red-900/30 rounded-xl transition-colors"
            >清仓</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── 添加/编辑表单 ─────────────────────────────────────────────────────────────
const EMPTY_FORM = {
  symbol: '', name: '', buy_date: new Date().toISOString().slice(0, 10),
  buy_price: '', quantity: '', stop_loss: '', target_price: '', notes: '',
}

function PositionForm({
  initial, onSave, onClose,
}: {
  initial?: Position
  onSave: (data: Record<string, unknown>) => void
  onClose: () => void
}) {
  const [form, setForm] = useState(initial ? {
    symbol: initial.symbol, name: initial.name,
    buy_date: initial.buy_date,
    buy_price: String(initial.buy_price),
    quantity: String(initial.quantity),
    stop_loss: initial.stop_loss ? String(initial.stop_loss) : '',
    target_price: initial.target_price ? String(initial.target_price) : '',
    notes: initial.notes ?? '',
  } : { ...EMPTY_FORM })

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = () => {
    if (!form.symbol || !form.buy_price || !form.quantity) return
    onSave({
      symbol: form.symbol, name: form.name,
      buy_date: form.buy_date,
      buy_price: parseFloat(form.buy_price),
      quantity: parseFloat(form.quantity),
      stop_loss: parseFloat(form.stop_loss || '0') || 0,
      target_price: parseFloat(form.target_price || '0') || 0,
      notes: form.notes,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-md mx-4 mb-4 sm:mb-0 overflow-hidden"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h3 className="text-sm font-semibold text-white">{initial ? '编辑持仓' : '新增持仓'}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-lg">×</button>
        </div>

        <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
          {/* 股票搜索 */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-500">股票</label>
            {initial ? (
              <div className="bg-gray-800 rounded-xl px-3 py-2.5 text-sm text-gray-300">
                {initial.name} ({initial.symbol})
              </div>
            ) : (
              <StockSearch
                value={form.symbol}
                onChange={(sym, name) => { set('symbol', sym); set('name', name) }}
                placeholder="搜索股票代码/名称/拼音"
              />
            )}
          </div>

          {/* 日期 */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-500">买入日期</label>
            <input type="date" value={form.buy_date}
              onChange={e => set('buy_date', e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white"/>
          </div>

          {/* 成本 & 数量 */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs text-gray-500">买入均价（元）</label>
              <input type="number" placeholder="0.00" value={form.buy_price}
                onChange={e => set('buy_price', e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white"/>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-gray-500">持股数量（股）</label>
              <input type="number" placeholder="100" value={form.quantity}
                onChange={e => set('quantity', e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white"/>
            </div>
          </div>

          {/* 止损 & 目标 */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs text-gray-500">止损价（可选）</label>
              <input type="number" placeholder="不设止损" value={form.stop_loss}
                onChange={e => set('stop_loss', e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white"/>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-gray-500">目标价（可选）</label>
              <input type="number" placeholder="不设目标" value={form.target_price}
                onChange={e => set('target_price', e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white"/>
            </div>
          </div>

          {/* 备注 */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-500">买入理由/备注</label>
            <textarea placeholder="为什么买入这支股票？主要逻辑是什么？" value={form.notes}
              onChange={e => set('notes', e.target.value)} rows={2}
              className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white resize-none"/>
          </div>

          {/* 预览成本 */}
          {form.buy_price && form.quantity && (
            <div className="bg-blue-950/20 border border-blue-900/30 rounded-xl px-3 py-2 text-xs text-gray-400">
              持仓成本：{fmt(parseFloat(form.buy_price) * parseFloat(form.quantity))}
            </div>
          )}
        </div>

        <div className="px-5 pb-5 flex gap-3">
          <button onClick={onClose}
            className="flex-1 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded-xl text-sm transition-colors">
            取消
          </button>
          <button onClick={handleSubmit}
            disabled={!form.symbol || !form.buy_price || !form.quantity}
            className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-40">
            {initial ? '保存修改' : '记录持仓'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── 截图识别导入 ──────────────────────────────────────────────────────────────
interface ParsedPos {
  name: string; symbol: string
  quantity: number; cost_price: number; current_price: number
}

function ScreenshotImport({ onImported }: { onImported: () => void }) {
  const [step, setStep] = useState<'idle'|'recognizing'|'preview'|'importing'>('idle')
  const [parsed, setParsed] = useState<ParsedPos[]>([])
  const [preview, setPreview] = useState<string>('')
  const [error, setError] = useState('')
  const [editRows, setEditRows] = useState<Array<ParsedPos & { buy_date: string; include: boolean }>>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const dropRef = useRef<HTMLDivElement>(null)

  const today = new Date().toISOString().slice(0, 10)

  const processFile = useCallback(async (file: File) => {
    setError('')
    setStep('recognizing')

    // 显示预览图
    const reader = new FileReader()
    reader.onload = e => setPreview(e.target?.result as string)
    reader.readAsDataURL(file)

    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch('/api/portfolio/parse-screenshot', {
        method: 'POST', body: fd,
      })
      const data = await r.json()
      if (!r.ok || data.error) {
        setError(data.error || '识别失败，请重试')
        setStep('idle')
        return
      }
      const rows = (data.positions as ParsedPos[]).map(p => ({
        ...p, buy_date: today, include: true,
      }))
      setParsed(data.positions)
      setEditRows(rows)
      setStep('preview')
    } catch {
      setError('网络错误，请检查后端服务')
      setStep('idle')
    }
  }, [today])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file && file.type.startsWith('image/')) processFile(file)
  }, [processFile])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) processFile(file)
  }

  const setRow = (i: number, key: string, val: unknown) => {
    setEditRows(rows => rows.map((r, idx) => idx === i ? { ...r, [key]: val } : r))
  }

  const handleImport = async () => {
    const toImport = editRows.filter(r => r.include && r.symbol && r.cost_price > 0 && r.quantity > 0)
    if (!toImport.length) { setError('没有可导入的有效持仓（请检查代码/成本/数量是否填写）'); return }
    setStep('importing')
    try {
      const r = await fetch('/api/portfolio/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          positions: toImport.map(p => ({
            symbol: p.symbol, name: p.name,
            buy_date: p.buy_date,
            buy_price: p.cost_price,
            quantity: p.quantity,
            stop_loss: 0, target_price: 0, notes: '从截图导入',
          }))
        })
      })
      const data = await r.json()
      if (data.ok) {
        setStep('idle')
        setParsed([])
        setEditRows([])
        setPreview('')
        onImported()
      }
    } catch {
      setError('导入失败，请重试')
      setStep('preview')
    }
  }

  const reset = () => {
    setStep('idle'); setParsed([]); setEditRows([]); setPreview(''); setError('')
  }

  // ── idle: 上传区 ──
  if (step === 'idle') return (
    <div>
      <div
        ref={dropRef}
        onDragOver={e => e.preventDefault()}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className="border-2 border-dashed border-gray-700 hover:border-blue-600 rounded-2xl p-8 text-center cursor-pointer transition-colors group"
      >
        <div className="text-4xl mb-3 group-hover:scale-110 transition-transform">📷</div>
        <p className="text-sm text-gray-300 font-medium">截图识别导入</p>
        <p className="text-xs text-gray-600 mt-1">点击上传 或 拖拽截图到此处</p>
        <p className="text-[10px] text-gray-700 mt-2">支持东方财富、同花顺、华泰等券商 App 持仓截图</p>
      </div>
      <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
      {error && <p className="text-red-400 text-xs mt-2 text-center">{error}</p>}
    </div>
  )

  // ── recognizing: AI识别中 ──
  if (step === 'recognizing') return (
    <div className="border-2 border-dashed border-blue-800/50 rounded-2xl p-8 text-center space-y-4">
      {preview && (
        <img src={preview} alt="截图预览" className="max-h-48 mx-auto rounded-xl object-contain opacity-60"/>
      )}
      <div className="flex flex-col items-center gap-2">
        <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"/>
        <p className="text-sm text-blue-400">AI 正在识别持仓数据…</p>
        <p className="text-xs text-gray-600">通常需要 3-8 秒</p>
      </div>
    </div>
  )

  // ── preview: 确认/编辑 ──
  if (step === 'preview') return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-white">识别结果 · 请确认</p>
          <p className="text-xs text-gray-500 mt-0.5">识别到 {parsed.length} 支持仓，可编辑后确认导入</p>
        </div>
        <button onClick={reset} className="text-xs text-gray-600 hover:text-gray-400">重新上传</button>
      </div>

      {preview && (
        <img src={preview} alt="截图" className="w-full max-h-32 object-contain rounded-xl opacity-50"/>
      )}

      <div className="space-y-2">
        {editRows.map((row, i) => (
          <div key={i} className={`rounded-xl border p-3 space-y-2 transition-colors ${
            row.include ? 'border-gray-700 bg-gray-900/60' : 'border-gray-800/50 bg-gray-900/20 opacity-50'
          }`}>
            {/* 顶部：股票名 + 勾选 */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <input type="checkbox" checked={row.include}
                  onChange={e => setRow(i, 'include', e.target.checked)}
                  className="w-4 h-4 accent-blue-500"/>
                <span className="text-sm font-medium text-white">{row.name}</span>
              </div>
              {/* 代码 */}
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-gray-600">代码</span>
                <input
                  value={row.symbol}
                  onChange={e => setRow(i, 'symbol', e.target.value)}
                  placeholder="6位代码"
                  className="w-20 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white font-mono text-center"
                />
              </div>
            </div>

            {/* 数据行 */}
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1">
                <p className="text-[10px] text-gray-600">买入均价（元）</p>
                <input type="number"
                  value={row.cost_price}
                  onChange={e => setRow(i, 'cost_price', parseFloat(e.target.value) || 0)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-white"
                />
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-gray-600">持股数量（股）</p>
                <input type="number"
                  value={row.quantity}
                  onChange={e => setRow(i, 'quantity', parseInt(e.target.value) || 0)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-white"
                />
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-gray-600">买入日期</p>
                <input type="date"
                  value={row.buy_date}
                  onChange={e => setRow(i, 'buy_date', e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-white"
                />
              </div>
            </div>

            {/* 实时现价 + 浮盈估算 */}
            {row.current_price > 0 && (
              <p className="text-[10px] text-gray-400">
                <span className="text-blue-400 font-medium">实时现价 ¥{row.current_price.toFixed(3)}</span>
                {row.cost_price > 0 && (() => {
                  const pnlPct = ((row.current_price - row.cost_price) / row.cost_price) * 100
                  return (
                    <span className={pnlPct >= 0 ? 'text-red-400' : 'text-green-400'}>
                      {' · '}{pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                    </span>
                  )
                })()}
              </p>
            )}
          </div>
        ))}
      </div>

      {error && <p className="text-red-400 text-xs text-center">{error}</p>}

      <div className="flex gap-3 pt-1">
        <button onClick={reset}
          className="flex-1 py-3 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded-xl text-sm transition-colors">
          取消
        </button>
        <button
          onClick={handleImport}
          disabled={!editRows.some(r => r.include)}
          className="flex-1 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-semibold transition-colors disabled:opacity-40"
        >
          确认导入 {editRows.filter(r => r.include).length} 支持仓
        </button>
      </div>
    </div>
  )

  // ── importing ──
  return (
    <div className="py-8 text-center space-y-2">
      <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto"/>
      <p className="text-sm text-gray-400">正在导入…</p>
    </div>
  )
}

// ── 候选池 ────────────────────────────────────────────────────────────────────
function CandidatePool() {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ symbol: '', name: '', reason: '', target_entry: '' })

  const { data } = useQuery<CandidateResp>({
    queryKey: ['candidates'],
    queryFn: async () => (await fetch('/api/portfolio/candidates')).json(),
    staleTime: 60_000,
  })

  const { mutate: addCand } = useMutation({
    mutationFn: async (d: object) => {
      await fetch('/api/portfolio/candidates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(d),
      })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['candidates'] }); setAdding(false); setForm({ symbol: '', name: '', reason: '', target_entry: '' }) },
  })

  const { mutate: removeCand } = useMutation({
    mutationFn: async (sym: string) => {
      await fetch(`/api/portfolio/candidates/${sym}`, { method: 'DELETE' })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['candidates'] }),
  })

  const candidates = data?.candidates ?? []

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-200">🔭 候选池</p>
          <p className="text-[10px] text-gray-600">研究中的股票，条件成熟时转为持仓</p>
        </div>
        <button onClick={() => setAdding(true)}
          className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-400 border border-gray-700 px-3 py-1.5 rounded-xl transition-colors">
          + 加入候选
        </button>
      </div>

      {candidates.length === 0 ? (
        <div className="text-center py-6 text-gray-700 text-xs">
          候选池为空 · 从「今日推荐」或自己研究的股票中加入
        </div>
      ) : (
        <div className="space-y-2">
          {candidates.map(c => (
            <div key={c.symbol} className="flex items-center gap-3 bg-gray-900/60 border border-gray-800 rounded-xl px-4 py-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-medium text-white">{c.name}</span>
                  <span className="text-[10px] text-gray-600 font-mono">{c.symbol}</span>
                </div>
                {c.reason && <p className="text-[10px] text-gray-500 mt-0.5 truncate">{c.reason}</p>}
              </div>
              <div className="text-right shrink-0">
                <p className="text-sm font-mono text-white">¥{c.current_price.toFixed(2)}</p>
                <p className={`text-[10px] font-mono ${pctColor(c.pct_change)}`}>
                  {c.pct_change > 0 ? '+' : ''}{c.pct_change.toFixed(2)}%
                </p>
              </div>
              {c.target_entry > 0 && (
                <div className="text-right shrink-0">
                  <p className="text-[9px] text-gray-600">目标入场</p>
                  <p className="text-xs text-blue-400 font-mono">¥{c.target_entry.toFixed(2)}</p>
                </div>
              )}
              <button onClick={() => removeCand(c.symbol)}
                className="text-gray-700 hover:text-red-400 transition-colors text-sm shrink-0">✕</button>
            </div>
          ))}
        </div>
      )}

      {/* 添加候选表单 */}
      {adding && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => setAdding(false)}>
          <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-md mx-4 mb-4 sm:mb-0 overflow-hidden"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
              <h3 className="text-sm font-semibold text-white">加入候选池</h3>
              <button onClick={() => setAdding(false)} className="text-gray-500 text-lg">×</button>
            </div>
            <div className="p-5 space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs text-gray-500">股票</label>
                <StockSearch
                  value={form.symbol}
                  onChange={(sym, name) => setForm(f => ({ ...f, symbol: sym, name }))}
                  placeholder="搜索股票代码/名称/拼音"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs text-gray-500">关注理由</label>
                <input placeholder="为什么关注这支股票？" value={form.reason}
                  onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white"/>
              </div>
              <div className="space-y-1.5">
                <label className="text-xs text-gray-500">目标入场价（可选）</label>
                <input type="number" placeholder="回调到此价位考虑入场" value={form.target_entry}
                  onChange={e => setForm(f => ({ ...f, target_entry: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white"/>
              </div>
              <div className="flex gap-3">
                <button onClick={() => setAdding(false)}
                  className="flex-1 py-2.5 bg-gray-800 text-gray-400 rounded-xl text-sm">取消</button>
                <button
                  onClick={() => addCand({ ...form, target_entry: parseFloat(form.target_entry || '0') || 0 })}
                  disabled={!form.symbol}
                  className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm disabled:opacity-40">
                  加入候选池
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

// ── 今日操作记录（交易日志） ──────────────────────────────────────────────────
function gradeColor(grade: string) {
  switch (grade) {
    case 'A': return 'text-emerald-400 border-emerald-700/50 bg-emerald-950/40'
    case 'B': return 'text-sky-400 border-sky-700/50 bg-sky-950/40'
    case 'C': return 'text-amber-400 border-amber-700/50 bg-amber-950/40'
    default:  return 'text-rose-400 border-rose-700/50 bg-rose-950/40'
  }
}

function TradeCard({ t, onDelete, onReanalyze }: {
  t: Trade
  onDelete: (id: string) => void
  onReanalyze: (id: string) => void
}) {
  const isBuy = t.action === 'buy'
  const time = t.at.slice(11, 16)
  const amount = t.price * t.quantity

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-3.5 space-y-2.5">
      {/* 头部：方向 + 股票 + 时间 */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-[10px] font-bold px-2 py-1 rounded-lg shrink-0 ${
            isBuy ? 'bg-red-900/50 text-red-300' : 'bg-emerald-900/50 text-emerald-300'
          }`}>
            {isBuy ? '买入' : '卖出'}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white truncate">{t.name || t.symbol}</p>
            <p className="text-[10px] text-gray-600 font-mono">{t.symbol}</p>
          </div>
        </div>
        <div className="text-right shrink-0">
          <p className="text-[10px] text-gray-500">{time}</p>
          {!t.position_synced && <p className="text-[9px] text-gray-700">未同步持仓</p>}
        </div>
      </div>

      {/* 成交详情 */}
      <div className="grid grid-cols-3 gap-2 text-center bg-gray-950/50 rounded-xl py-2">
        <div>
          <p className="text-[9px] text-gray-600">数量</p>
          <p className="text-xs font-mono text-gray-200 mt-0.5">{t.quantity}股</p>
        </div>
        <div>
          <p className="text-[9px] text-gray-600">成交价</p>
          <p className="text-xs font-mono text-gray-200 mt-0.5">¥{t.price}</p>
        </div>
        <div>
          <p className="text-[9px] text-gray-600">金额</p>
          <p className="text-xs font-mono text-gray-200 mt-0.5">{fmt(amount)}</p>
        </div>
      </div>

      {/* 操作理由 */}
      {t.reason && (
        <p className="text-xs text-gray-400 leading-relaxed bg-gray-950/40 rounded-xl px-3 py-2">
          💭 {t.reason}
        </p>
      )}

      {/* AI 评分 */}
      {t.ai_status === 'processing' && (
        <div className="flex items-center gap-2 text-[11px] text-gray-500 px-1">
          <div className="w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"/>
          AI 正在分析这笔操作…
        </div>
      )}
      {t.ai_status === 'error' && (
        <div className="flex items-center justify-between text-[11px] text-rose-400 px-1">
          <span>AI 分析失败{t.ai_error ? `：${t.ai_error}` : ''}</span>
          <button onClick={() => onReanalyze(t.id)} className="text-blue-400 hover:text-blue-300">重试</button>
        </div>
      )}
      {t.ai_status === 'done' && t.ai && (
        <div className="border-t border-gray-800 pt-2.5 space-y-2">
          <div className="flex items-center gap-2.5">
            <div className={`flex flex-col items-center justify-center w-12 h-12 rounded-xl border ${gradeColor(t.ai.grade)} shrink-0`}>
              <span className="text-lg font-bold leading-none">{t.ai.score}</span>
              <span className="text-[9px] font-semibold mt-0.5">{t.ai.grade}级</span>
            </div>
            <p className="text-xs text-gray-300 font-medium leading-snug flex-1">{t.ai.summary}</p>
          </div>
          {t.ai.pros.length > 0 && (
            <div className="space-y-0.5">
              {t.ai.pros.map((p, i) => (
                <p key={i} className="text-[11px] text-emerald-400/90 leading-relaxed">✓ {p}</p>
              ))}
            </div>
          )}
          {t.ai.cons.length > 0 && (
            <div className="space-y-0.5">
              {t.ai.cons.map((c, i) => (
                <p key={i} className="text-[11px] text-amber-400/90 leading-relaxed">△ {c}</p>
              ))}
            </div>
          )}
          {t.ai.advice && (
            <p className="text-[11px] text-blue-300/90 bg-blue-950/30 border border-blue-900/40 rounded-lg px-2.5 py-1.5 leading-relaxed">
              🎯 {t.ai.advice}
            </p>
          )}
        </div>
      )}

      {/* 操作 */}
      <div className="flex justify-end gap-3 pt-0.5">
        {t.ai_status === 'done' && (
          <button onClick={() => onReanalyze(t.id)} className="text-[10px] text-gray-600 hover:text-gray-400">重新评分</button>
        )}
        <button onClick={() => onDelete(t.id)} className="text-[10px] text-gray-600 hover:text-rose-400">删除</button>
      </div>
    </div>
  )
}

function TradeJournalPanel() {
  const qc = useQueryClient()
  const [action, setAction]   = useState<'buy' | 'sell'>('buy')
  const [symbol, setSymbol]   = useState('')
  const [name, setName]       = useState('')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice]     = useState('')
  const [reason, setReason]   = useState('')
  const [syncPos, setSyncPos] = useState(true)

  // 有处理中的记录时轮询
  const { data } = useQuery<TradesResp>({
    queryKey: ['portfolio-trades'],
    queryFn: async () => (await fetch('/api/portfolio/trades')).json(),
    refetchInterval: (q) => {
      const trades = (q.state.data as TradesResp | undefined)?.trades ?? []
      return trades.some(t => t.ai_status === 'processing') ? 2500 : false
    },
  })

  const { mutate: addTrade, isPending } = useMutation({
    mutationFn: async (body: object) => {
      const r = await fetch('/api/portfolio/trades', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error((await r.json()).error || '提交失败')
      return r.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portfolio-trades'] })
      if (syncPos) qc.invalidateQueries({ queryKey: ['portfolio'] })
      setQuantity(''); setPrice(''); setReason('')   // 保留股票，方便连续记录
    },
  })

  const { mutate: delTrade } = useMutation({
    mutationFn: async (id: string) => { await fetch(`/api/portfolio/trades/${id}`, { method: 'DELETE' }) },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio-trades'] }),
  })

  const { mutate: reanalyze } = useMutation({
    mutationFn: async (id: string) => { await fetch(`/api/portfolio/trades/${id}/reanalyze`, { method: 'POST' }) },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio-trades'] }),
  })

  const trades  = data?.trades ?? []
  const summary = data?.summary
  const qtyNum  = parseInt(quantity || '0', 10) || 0
  const canSubmit = symbol && qtyNum > 0 && parseFloat(price) > 0

  const submit = () => {
    if (!canSubmit) return
    addTrade({
      symbol, name, action,
      quantity: parseFloat(quantity),
      price: parseFloat(price),
      reason,
      update_position: syncPos,
    })
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-white">📝 今日操作记录</h2>
          <p className="text-[10px] text-gray-600 mt-0.5">记下每笔买卖与理由，AI 实时打分复盘</p>
        </div>
        {summary && summary.avg_score != null && (
          <div className="text-right">
            <p className="text-[9px] text-gray-600">今日均分</p>
            <p className="text-base font-bold text-white font-mono">{summary.avg_score}</p>
          </div>
        )}
      </div>

      {/* 录入表单 */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 space-y-3">
        {/* 买/卖切换 */}
        <div className="grid grid-cols-2 gap-2">
          <button onClick={() => setAction('buy')}
            className={`py-2 rounded-xl text-sm font-semibold transition-colors ${
              action === 'buy' ? 'bg-red-600/30 text-red-300 border border-red-700/50' : 'bg-gray-800 text-gray-500 border border-transparent'
            }`}>买入</button>
          <button onClick={() => setAction('sell')}
            className={`py-2 rounded-xl text-sm font-semibold transition-colors ${
              action === 'sell' ? 'bg-emerald-600/30 text-emerald-300 border border-emerald-700/50' : 'bg-gray-800 text-gray-500 border border-transparent'
            }`}>卖出</button>
        </div>

        <StockSearch
          value={symbol}
          defaultName={name}
          placeholder="搜索股票（代码/名称）"
          onChange={(s, n) => { setSymbol(s); setName(n) }}
        />

        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <div className="flex items-baseline justify-between">
              <label className="text-[10px] text-gray-500">数量</label>
              {qtyNum > 0 && (
                <span className={`text-[10px] font-mono ${qtyNum % 100 === 0 ? 'text-gray-500' : 'text-amber-500'}`}>
                  {qtyNum % 100 === 0 ? `${qtyNum / 100} 手` : `含零股`}
                </span>
              )}
            </div>
            <div className="flex items-center gap-1.5">
              <button type="button" onClick={() => setQuantity(String(Math.max(0, qtyNum - 100)))}
                className="w-8 shrink-0 bg-gray-800 border border-gray-700 rounded-lg text-gray-400 hover:bg-gray-700 text-sm py-2">−</button>
              <input type="number" inputMode="numeric" step={100} placeholder="股数" value={quantity}
                onChange={e => setQuantity(e.target.value)}
                className="w-full min-w-0 bg-gray-800 border border-gray-700 rounded-xl px-2 py-2 text-sm text-white text-center"/>
              <button type="button" onClick={() => setQuantity(String(qtyNum + 100))}
                className="w-8 shrink-0 bg-gray-800 border border-gray-700 rounded-lg text-gray-400 hover:bg-gray-700 text-sm py-2">＋</button>
            </div>
            <div className="flex gap-1">
              {[100, 500, 1000].map(n => (
                <button key={n} type="button" onClick={() => setQuantity(String(qtyNum + n))}
                  className="flex-1 text-[10px] text-gray-500 hover:text-gray-300 bg-gray-800/60 hover:bg-gray-700 rounded-md py-1">
                  +{n / 100}手
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-[10px] text-gray-500">成交价（¥）</label>
            <input type="number" inputMode="decimal" placeholder="当时价格" value={price}
              onChange={e => setPrice(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-sm text-white"/>
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-[10px] text-gray-500">为什么这么操作？</label>
          <textarea placeholder="如：突破平台放量，按计划建仓 1/3 …" value={reason} rows={2}
            onChange={e => setReason(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-sm text-white resize-none"/>
        </div>

        <label className="flex items-center gap-2 text-[11px] text-gray-500 cursor-pointer select-none">
          <input type="checkbox" checked={syncPos} onChange={e => setSyncPos(e.target.checked)}
            className="accent-blue-500"/>
          同时更新到持仓（买入加仓/卖出减仓，自动算成本）
        </label>

        <button onClick={submit} disabled={!canSubmit || isPending}
          className={`w-full py-2.5 rounded-xl text-sm font-semibold transition-colors disabled:opacity-40 ${
            action === 'buy' ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-emerald-600 hover:bg-emerald-500 text-white'
          }`}>
          {isPending ? '记录中…' : `记录${action === 'buy' ? '买入' : '卖出'}并 AI 评分`}
        </button>
      </div>

      {/* 当日小结 */}
      {summary && summary.count > 0 && (
        <div className="grid grid-cols-3 gap-2 bg-gray-900/60 border border-gray-800 rounded-2xl p-3 text-center">
          <div>
            <p className="text-[9px] text-gray-600">操作笔数</p>
            <p className="text-sm font-mono text-gray-200 mt-0.5">{summary.count}</p>
          </div>
          <div>
            <p className="text-[9px] text-gray-600">买入额</p>
            <p className="text-sm font-mono text-red-400 mt-0.5">{fmt(summary.buy_amount)}</p>
          </div>
          <div>
            <p className="text-[9px] text-gray-600">卖出额</p>
            <p className="text-sm font-mono text-emerald-400 mt-0.5">{fmt(summary.sell_amount)}</p>
          </div>
        </div>
      )}

      {/* 操作列表 */}
      {trades.length === 0 ? (
        <div className="text-center py-10 text-xs text-gray-600">
          今天还没有操作记录<br/>
          <span className="text-gray-700">买卖后记一笔，让 AI 帮你复盘</span>
        </div>
      ) : (
        <div className="space-y-3">
          {trades.map(t => (
            <TradeCard key={t.id} t={t} onDelete={delTrade} onReanalyze={reanalyze} />
          ))}
        </div>
      )}
    </section>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────
export default function PortfolioPage() {
  const qc = useQueryClient()
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Position | undefined>()
  const [showImport, setShowImport] = useState(false)

  const market = getMarketStatus()

  const { data, isLoading, refetch } = useQuery<PortfolioResp>({
    queryKey: ['portfolio'],
    queryFn: async () => (await fetch('/api/portfolio')).json(),
    staleTime: typeof market.interval === 'number' ? market.interval : Infinity,
    refetchInterval: market.interval,
    // 窗口重新聚焦时也刷新（切回来时立刻看到最新价）
    refetchOnWindowFocus: market.open,
  })

  const { mutate: savePosition } = useMutation({
    mutationFn: async (d: object) => {
      await fetch('/api/portfolio', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(d),
      })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['portfolio'] }); setFormOpen(false); setEditing(undefined) },
  })

  const { mutate: deletePosition } = useMutation({
    mutationFn: async (sym: string) => {
      await fetch(`/api/portfolio/${sym}`, { method: 'DELETE' })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio'] }),
  })

  // ── 卖点诊断 ──
  const { data: guidanceData } = useQuery<GuidanceResp>({
    queryKey: ['sell-guidance'],
    queryFn: async () => (await fetch('/api/portfolio/sell-guidance')).json(),
    refetchInterval: (q) => {
      const g = (q.state.data as GuidanceResp | undefined)?.guidance ?? {}
      return Object.values(g).some(x => x.status === 'processing') ? 2500 : false
    },
  })
  const guidanceMap = guidanceData?.guidance ?? {}

  const { mutate: runDiagnose } = useMutation({
    mutationFn: async (symbols: string[]) => {
      await fetch('/api/portfolio/sell-guidance', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols }),
      })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sell-guidance'] }),
  })

  const positions = data?.positions ?? []
  const summary   = data?.summary
  const alerts    = data?.alerts ?? []
  const anyDiagnosing = Object.values(guidanceMap).some(x => x.status === 'processing')

  // ── 盘中自动重诊：每5分钟用最新走势+量能重新诊断全部持仓；进页面时若结论过期(>6分钟)立即跑一次 ──
  const AUTO_REDIAGNOSE_MS = 5 * 60_000
  const STALE_GUIDANCE_MS  = 6 * 60_000
  const heldKey = positions.map(p => p.symbol).join(',')
  useEffect(() => {
    if (!market.open || !heldKey) return
    const heldSymbols = heldKey.split(',')
    const triggerIfIdle = () => {
      const g = qc.getQueryData<GuidanceResp>(['sell-guidance'])?.guidance ?? {}
      const processing = Object.values(g).some(x => x.status === 'processing')
      if (!processing) runDiagnose(heldSymbols)
    }
    // 开盘/进页面：结论缺失或过期则立即重诊
    const g = qc.getQueryData<GuidanceResp>(['sell-guidance'])?.guidance ?? {}
    const stale = heldSymbols.some(s => {
      const e = g[s]
      if (!e || !e.at || e.status === 'error') return true
      return Date.now() - new Date(e.at).getTime() > STALE_GUIDANCE_MS
    })
    if (stale) triggerIfIdle()
    const id = setInterval(triggerIfIdle, AUTO_REDIAGNOSE_MS)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market.open, heldKey])

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-6xl mx-auto px-4 py-5">
       <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-start">
        {/* ── 左侧：持仓 ── */}
        <div className="lg:col-span-2 space-y-5">

        {/* 标题栏 */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-white">持仓管理</h1>
              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full border ${
                market.open
                  ? 'text-green-400 border-green-800 bg-green-950/50'
                  : 'text-gray-500 border-gray-700 bg-gray-900/50'
              }`}>
                {market.open ? '● ' : '○ '}{market.label}
              </span>
            </div>
            <p className="text-[10px] text-gray-600 mt-0.5">
              {data?.updated_at ? `更新于 ${data.updated_at}` : '加载中…'}
              {' · '}
              <span className="text-gray-700">
                {market.open ? '每15秒自动刷新' : market.label === '集合竞价' ? '每30秒刷新' : '收盘后不自动刷新'}
              </span>
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => refetch()}
              className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-400 border border-gray-700 px-3 py-1.5 rounded-xl transition-colors">
              刷新
            </button>
            <button
              onClick={() => setShowImport(v => !v)}
              className={`text-xs border px-3 py-1.5 rounded-xl transition-colors ${
                showImport
                  ? 'bg-amber-600/30 text-amber-400 border-amber-700/50'
                  : 'bg-gray-800 hover:bg-gray-700 text-gray-400 border-gray-700'
              }`}
            >
              📷 截图导入
            </button>
            <button onClick={() => { setEditing(undefined); setFormOpen(true) }}
              className="text-xs bg-blue-600/30 hover:bg-blue-600/50 text-blue-400 border border-blue-700/50 px-3 py-1.5 rounded-xl transition-colors">
              + 手动录入
            </button>
          </div>
        </div>

        {/* 截图导入区 */}
        {showImport && (
          <div className="bg-gray-900 border border-amber-900/40 rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-sm font-semibold text-amber-300">📷 截图识别导入</p>
                <p className="text-[10px] text-gray-500 mt-0.5">上传券商 App 持仓截图，AI 自动识别并填入所有持仓</p>
              </div>
              <button onClick={() => setShowImport(false)} className="text-gray-600 hover:text-gray-400 text-lg">×</button>
            </div>
            <ScreenshotImport onImported={() => {
              setShowImport(false)
              qc.invalidateQueries({ queryKey: ['portfolio'] })
            }} />
          </div>
        )}

        {/* 警报 */}
        {alerts.length > 0 && (
          <div className="space-y-1.5">
            {alerts.map((a, i) => (
              <div key={i} className={`px-4 py-2.5 rounded-xl text-xs font-medium ${
                a.type === 'stop_loss' ? 'bg-red-900/40 text-red-300 border border-red-800/50'
                : 'bg-amber-900/30 text-amber-300 border border-amber-800/40'
              }`}>{a.message}</div>
            ))}
          </div>
        )}

        {/* 除权除息待应用提醒 */}
        <DividendAdjustPanel onApplied={() => qc.invalidateQueries({ queryKey: ['portfolio'] })} />

        {/* 总览 */}
        {summary && summary.position_count > 0 && (
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-4">
            <p className="text-[10px] text-gray-600 font-semibold uppercase tracking-widest">投资组合总览</p>
            <div className="flex items-end justify-between">
              <div>
                <p className="text-[10px] text-gray-500 mb-0.5">总市值</p>
                <p className="text-2xl font-bold text-white font-mono">{fmt(summary.total_value)}</p>
              </div>
              <div className="text-right">
                <p className={`text-xl font-bold font-mono ${pctColor(summary.total_pnl_pct)}`}>
                  {summary.total_pnl_pct > 0 ? '+' : ''}{summary.total_pnl_pct.toFixed(2)}%
                </p>
                <p className={`text-sm font-mono ${pctColor(summary.total_pnl_amount)}`}>
                  {summary.total_pnl_amount > 0 ? '+' : ''}{fmt(summary.total_pnl_amount)}
                </p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3 pt-1 border-t border-gray-800">
              <div className="text-center">
                <p className="text-[10px] text-gray-600">持仓成本</p>
                <p className="text-xs font-mono text-gray-300 mt-0.5">{fmt(summary.total_cost)}</p>
              </div>
              <div className="text-center">
                <p className="text-[10px] text-gray-600">今日盈亏</p>
                <p className={`text-xs font-mono mt-0.5 ${pctColor(summary.today_pnl)}`}>
                  {summary.today_pnl > 0 ? '+' : ''}{fmt(summary.today_pnl)}
                </p>
              </div>
              <div className="text-center">
                <p className="text-[10px] text-gray-600">持仓只数</p>
                <p className="text-xs font-mono text-gray-300 mt-0.5">{summary.position_count} 支</p>
              </div>
            </div>
          </div>
        )}

        {/* 持仓列表 */}
        {isLoading ? (
          <div className="py-12 text-center">
            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-2"/>
            <p className="text-gray-600 text-xs">加载中…</p>
          </div>
        ) : positions.length === 0 ? (
          <EmptyState onAdd={() => setFormOpen(true)} />
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-[10px] text-gray-600 font-semibold uppercase tracking-widest">
                持仓明细（{positions.length}支）
              </p>
              <button
                onClick={() => runDiagnose(positions.map(p => p.symbol))}
                disabled={anyDiagnosing}
                className="text-[11px] bg-purple-950/40 hover:bg-purple-900/50 text-purple-300 border border-purple-800/50 px-3 py-1.5 rounded-xl transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {anyDiagnosing
                  ? <><span className="w-3 h-3 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"/>诊断中…</>
                  : <>🩺 一键卖点体检</>}
              </button>
            </div>
            <p className="text-[10px] text-gray-700 -mt-1">
              会卖是师傅 · 以<span className="text-gray-500">当前走势+量能</span>为主、结合脑库卖出规则给建议（盈亏只定调止盈/止损）
              {market.open && <span className="text-purple-700"> · 盘中每5分钟自动重诊</span>}
            </p>
            {positions.map(p => (
              <PositionCard key={p.symbol} p={p}
                onEdit={pos => { setEditing(pos); setFormOpen(true) }}
                onDelete={sym => deletePosition(sym)}
                guidance={guidanceMap[p.symbol]}
                onDiagnose={sym => runDiagnose([sym])}
              />
            ))}
          </div>
        )}

        {/* 候选池 */}
        <div className="border-t border-gray-800/50 pt-5">
          <CandidatePool />
        </div>

        {/* 说明 */}
        <div className="text-center text-[10px] text-gray-700 space-y-0.5 pb-4">
          <p>持仓数据仅存储在本地 · 不会上传任何服务器</p>
          <p>止损/目标触达时页面会自动高亮提醒</p>
        </div>
        </div>

        {/* ── 右侧：今日操作记录 ── */}
        <div className="lg:col-span-1">
          <div className="lg:sticky lg:top-20">
            <TradeJournalPanel />
          </div>
        </div>
       </div>
      </div>

      {/* 表单弹窗 */}
      {formOpen && (
        <PositionForm
          initial={editing}
          onSave={d => savePosition(d)}
          onClose={() => { setFormOpen(false); setEditing(undefined) }}
        />
      )}
    </div>
  )
}
