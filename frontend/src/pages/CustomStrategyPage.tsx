/**
 * 我的策略 - 自定义量化策略
 * 可视化规则构建 + JS 代码编辑器 + 本地保存 + 回测
 */
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import StockSearch from '../components/StockSearch'
import type { OhlcvBar } from '../types'

// ── Types ─────────────────────────────────────────────────────────────────────

type IndicatorKey =
  | 'close' | 'open' | 'high' | 'low' | 'volume'
  | 'ma5' | 'ma10' | 'ma20' | 'ma60'
  | 'rsi14' | 'bb_upper' | 'bb_lower'

type Operator = 'gt' | 'lt' | 'gte' | 'lte' | 'cross_above' | 'cross_below'
type RhsType  = 'indicator' | 'value'

interface Condition {
  lhs:          IndicatorKey
  op:           Operator
  rhsType:      RhsType
  rhsIndicator: IndicatorKey
  rhsValue:     number
}

interface CustomStrategy {
  id:        string
  name:      string
  desc:      string
  mode:      'visual' | 'code'
  buyConds:  Condition[]
  sellConds: Condition[]
  code:      string
  createdAt: string
}

interface BacktestResult {
  equity:      { date: string; value: number; baseline: number }[]
  totalReturn: number
  maxDrawdown: number
  winRate:     number
  trades:      number
  sharpe:      number
  vsBaseline:  number
}

interface OhlcvResponse { ohlcv: OhlcvBar[] }

// ── Constants ─────────────────────────────────────────────────────────────────

const INDICATOR_LABELS: Record<IndicatorKey, string> = {
  close:    '收盘价',
  open:     '开盘价',
  high:     '最高价',
  low:      '最低价',
  volume:   '成交量',
  ma5:      'MA5',
  ma10:     'MA10',
  ma20:     'MA20',
  ma60:     'MA60',
  rsi14:    'RSI(14)',
  bb_upper: '布林上轨',
  bb_lower: '布林下轨',
}

const OPERATOR_LABELS: Record<Operator, string> = {
  gt:          '大于 (>)',
  lt:          '小于 (<)',
  gte:         '≥',
  lte:         '≤',
  cross_above: '上穿 ↑',
  cross_below: '下穿 ↓',
}

const INDICATOR_KEYS = Object.keys(INDICATOR_LABELS) as IndicatorKey[]
const OPERATOR_KEYS  = Object.keys(OPERATOR_LABELS) as Operator[]
const LS_KEY = 'custom_strategies_v1'

// ── Helpers ───────────────────────────────────────────────────────────────────

const defaultCond = (): Condition => ({
  lhs: 'close', op: 'gt', rhsType: 'indicator', rhsIndicator: 'ma20', rhsValue: 0,
})

function loadStrategies(): CustomStrategy[] {
  try { return JSON.parse(localStorage.getItem(LS_KEY) ?? '[]') } catch { return [] }
}
function saveStrategies(s: CustomStrategy[]) {
  localStorage.setItem(LS_KEY, JSON.stringify(s))
}

function toDateStr(d: Date) {
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}
type DateRange = '3m' | '6m' | '1y'
function getDateRange(r: DateRange) {
  const end = new Date(), start = new Date()
  if (r === '3m') start.setMonth(start.getMonth() - 3)
  else if (r === '6m') start.setMonth(start.getMonth() - 6)
  else start.setFullYear(start.getFullYear() - 1)
  return { start: toDateStr(start), end: toDateStr(end) }
}

// ── Code generator ────────────────────────────────────────────────────────────

function generateCode(name: string, buyConds: Condition[], sellConds: Condition[]): string {
  const used = new Set<IndicatorKey>()
  ;[...buyConds, ...sellConds].forEach(c => {
    used.add(c.lhs)
    if (c.rhsType === 'indicator') used.add(c.rhsIndicator)
  })

  const needClose = [...used].some(k =>
    ['close','ma5','ma10','ma20','ma60','rsi14','bb_upper','bb_lower'].includes(k))

  const indLines: string[] = []
  if (needClose)       indLines.push(`  const close    = ohlcv.map(b => b.close);`)
  if (used.has('open'))    indLines.push(`  const open     = ohlcv.map(b => b.open);`)
  if (used.has('high'))    indLines.push(`  const high     = ohlcv.map(b => b.high);`)
  if (used.has('low'))     indLines.push(`  const low      = ohlcv.map(b => b.low);`)
  if (used.has('volume'))  indLines.push(`  const volume   = ohlcv.map(b => b.volume);`)
  if (used.has('ma5'))     indLines.push(`  const ma5      = calcMA(close, 5);`)
  if (used.has('ma10'))    indLines.push(`  const ma10     = calcMA(close, 10);`)
  if (used.has('ma20'))    indLines.push(`  const ma20     = calcMA(close, 20);`)
  if (used.has('ma60'))    indLines.push(`  const ma60     = calcMA(close, 60);`)
  if (used.has('rsi14'))   indLines.push(`  const rsi14    = calcRSI(close, 14);`)
  if (used.has('bb_upper') || used.has('bb_lower')) {
    indLines.push(`  const _bb      = calcBB(close, 20, 2);`)
    if (used.has('bb_upper')) indLines.push(`  const bb_upper = _bb.map(b => b ? b.upper : null);`)
    if (used.has('bb_lower')) indLines.push(`  const bb_lower = _bb.map(b => b ? b.lower : null);`)
  }

  function condExpr(c: Condition): string {
    const L  = `${c.lhs}[i]`,   LP = `${c.lhs}[i-1]`
    const R  = c.rhsType === 'value' ? String(c.rhsValue) : `${c.rhsIndicator}[i]`
    const RP = c.rhsType === 'value' ? String(c.rhsValue) : `${c.rhsIndicator}[i-1]`
    const nullOk = c.rhsType === 'value' ? `${L} !== null` : `${L} !== null && ${R} !== null`
    switch (c.op) {
      case 'gt':          return `(${nullOk} && ${L} > ${R})`
      case 'lt':          return `(${nullOk} && ${L} < ${R})`
      case 'gte':         return `(${nullOk} && ${L} >= ${R})`
      case 'lte':         return `(${nullOk} && ${L} <= ${R})`
      case 'cross_above': return `(${nullOk} && ${LP} !== null && ${RP} !== null && ${LP} < ${RP} && ${L} >= ${R})`
      case 'cross_below': return `(${nullOk} && ${LP} !== null && ${RP} !== null && ${LP} > ${RP} && ${L} <= ${R})`
    }
  }

  const buyExpr  = buyConds.length  ? buyConds.map(condExpr).join('\n        && ')  : 'false'
  const sellExpr = sellConds.length ? sellConds.map(condExpr).join('\n        && ') : 'false'

  return `// 策略：${name}
// 由可视化构建器自动生成，可自由修改
// 参数 ohlcv: [{date, open, high, low, close, volume}, ...]
// 返回 signals 数组，每项为 'BUY' | 'SELL' | null

function strategy(ohlcv) {

  // ── 指标计算工具 ───────────────────────────────────
  function calcMA(arr, n) {
    return arr.map((_, i) => {
      if (i < n - 1) return null;
      let s = 0;
      for (let j = i - n + 1; j <= i; j++) s += arr[j];
      return s / n;
    });
  }
  function calcRSI(arr, n) {
    const r = new Array(arr.length).fill(null);
    for (let i = n; i < arr.length; i++) {
      let g = 0, l = 0;
      for (let j = i - n + 1; j <= i; j++) {
        const d = arr[j] - arr[j - 1];
        if (d > 0) g += d; else l -= d;
      }
      r[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
    }
    return r;
  }
  function calcBB(arr, n, m) {
    const ma = calcMA(arr, n);
    return ma.map((avg, i) => {
      if (avg === null) return null;
      let v = 0;
      for (let j = i - n + 1; j <= i; j++) v += (arr[j] - avg) ** 2;
      const std = Math.sqrt(v / n);
      return { upper: avg + m * std, lower: avg - m * std };
    });
  }

  // ── 指标计算 ───────────────────────────────────────
${indLines.join('\n')}

  // ── 逐日生成信号 ───────────────────────────────────
  const signals = new Array(ohlcv.length).fill(null);
  for (let i = 1; i < ohlcv.length; i++) {
    const buySignal =
      ${buyExpr};
    const sellSignal =
      ${sellExpr};
    if (buySignal)       signals[i] = 'BUY';
    else if (sellSignal) signals[i] = 'SELL';
  }
  return signals;
}`
}

// ── Run custom backtest ───────────────────────────────────────────────────────

function runCustomBacktest(ohlcv: OhlcvBar[], code: string): BacktestResult {
  let fn: (o: OhlcvBar[]) => (string | null)[]
  try {
    // eslint-disable-next-line no-new-func
    fn = new Function(code + '\nreturn strategy;')() as typeof fn
  } catch (e) { throw new Error(`代码解析失败: ${e}`) }

  let signals: (string | null)[]
  try { signals = fn(ohlcv) }
  catch (e) { throw new Error(`策略运行失败: ${e}`) }

  let cash = 100, shares = 0, inPos = false, buyPrice = 0
  let trades = 0, wins = 0, peak = 100, maxDD = 0
  const rets: number[] = []
  const equity: BacktestResult['equity'] = []
  const base0 = ohlcv[0]?.close ?? 1

  for (let i = 0; i < ohlcv.length; i++) {
    const { date, close } = ohlcv[i]
    if (signals[i] === 'BUY' && !inPos) {
      shares = cash / close; cash = 0; inPos = true; buyPrice = close
    } else if (signals[i] === 'SELL' && inPos) {
      const ret = (close - buyPrice) / buyPrice
      rets.push(ret); if (ret > 0) wins++; trades++
      cash = shares * close; shares = 0; inPos = false
    }
    const val = cash + shares * close
    if (val > peak) peak = val
    const dd = (peak - val) / peak
    if (dd > maxDD) maxDD = dd
    equity.push({
      date,
      value:    parseFloat(val.toFixed(2)),
      baseline: parseFloat(((close / base0) * 100).toFixed(2)),
    })
  }

  const last = equity[equity.length - 1]
  const totalReturn = parseFloat(((last?.value ?? 100) - 100).toFixed(2))

  let sharpe = 0
  if (rets.length > 1) {
    const mean = rets.reduce((a, b) => a + b, 0) / rets.length
    const std  = Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length)
    sharpe = std > 0 ? parseFloat(((mean / std) * Math.sqrt(252)).toFixed(2)) : 0
  }

  return {
    equity,
    totalReturn,
    maxDrawdown: parseFloat((maxDD * 100).toFixed(2)),
    winRate:     trades > 0 ? parseFloat(((wins / trades) * 100).toFixed(1)) : 0,
    trades,
    sharpe,
    vsBaseline:  parseFloat((totalReturn - ((last?.baseline ?? 100) - 100)).toFixed(2)),
  }
}

// ── ConditionRow ──────────────────────────────────────────────────────────────

function ConditionRow({
  cond, onChange, onDelete,
}: {
  cond:     Condition
  onChange: (c: Condition) => void
  onDelete: () => void
}) {
  const sel = 'bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-300 outline-none focus:border-blue-500'

  return (
    <div className="flex items-center gap-2 flex-wrap bg-gray-800/40 rounded-lg p-2">
      {/* LHS */}
      <select value={cond.lhs} onChange={e => onChange({ ...cond, lhs: e.target.value as IndicatorKey })} className={sel}>
        {INDICATOR_KEYS.map(k => <option key={k} value={k}>{INDICATOR_LABELS[k]}</option>)}
      </select>

      {/* Operator */}
      <select value={cond.op} onChange={e => onChange({ ...cond, op: e.target.value as Operator })} className={sel}>
        {OPERATOR_KEYS.map(k => <option key={k} value={k}>{OPERATOR_LABELS[k]}</option>)}
      </select>

      {/* RHS type toggle */}
      <div className="flex rounded-lg overflow-hidden border border-gray-700 text-xs">
        <button
          onClick={() => onChange({ ...cond, rhsType: 'indicator' })}
          className={`px-2.5 py-1.5 transition-colors ${cond.rhsType === 'indicator' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
        >指标</button>
        <button
          onClick={() => onChange({ ...cond, rhsType: 'value' })}
          className={`px-2.5 py-1.5 transition-colors ${cond.rhsType === 'value' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
        >数值</button>
      </div>

      {/* RHS */}
      {cond.rhsType === 'indicator' ? (
        <select value={cond.rhsIndicator} onChange={e => onChange({ ...cond, rhsIndicator: e.target.value as IndicatorKey })} className={sel}>
          {INDICATOR_KEYS.map(k => <option key={k} value={k}>{INDICATOR_LABELS[k]}</option>)}
        </select>
      ) : (
        <input
          type="number"
          value={cond.rhsValue}
          onChange={e => onChange({ ...cond, rhsValue: parseFloat(e.target.value) || 0 })}
          className="w-20 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-300 outline-none focus:border-blue-500"
        />
      )}

      <button onClick={onDelete} className="text-gray-600 hover:text-red-400 transition-colors ml-auto pl-1 text-lg leading-none">×</button>
    </div>
  )
}

// ── StrategyEditor ────────────────────────────────────────────────────────────

function StrategyEditor({
  initial, onSave, onCancel,
}: {
  initial?:  CustomStrategy
  onSave:   (s: CustomStrategy) => void
  onCancel: () => void
}) {
  const [name,      setName]      = useState(initial?.name ?? '我的策略')
  const [desc,      setDesc]      = useState(initial?.desc ?? '')
  const [mode,      setMode]      = useState<'visual' | 'code'>(initial?.mode ?? 'visual')
  const [buyConds,  setBuyConds]  = useState<Condition[]>(initial?.buyConds  ?? [defaultCond()])
  const [sellConds, setSellConds] = useState<Condition[]>(initial?.sellConds ?? [{
    lhs: 'close', op: 'lt', rhsType: 'indicator', rhsIndicator: 'ma20', rhsValue: 0,
  }])
  const [code,  setCode]  = useState<string>(initial?.code ?? '')
  const [error, setError] = useState('')

  function switchToCode() {
    setCode(generateCode(name, buyConds, sellConds))
    setMode('code')
  }

  function handleSave() {
    if (!name.trim()) { setError('请输入策略名称'); return }
    const finalCode = mode === 'visual' ? generateCode(name, buyConds, sellConds) : code
    try {
      // eslint-disable-next-line no-new-func
      new Function(finalCode + '\nreturn strategy;')()
    } catch (e) { setError(`代码有误: ${e}`); return }
    setError('')
    onSave({
      id:        initial?.id ?? Date.now().toString(),
      name:      name.trim(),
      desc:      desc.trim(),
      mode,
      buyConds,
      sellConds,
      code:      finalCode,
      createdAt: initial?.createdAt ?? new Date().toISOString(),
    })
  }

  const condSection = (
    label: string,
    color: string,
    conds: Condition[],
    setConds: React.Dispatch<React.SetStateAction<Condition[]>>,
    emptyHint: string,
  ) => (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className={`text-sm font-medium ${color}`}>{label}</span>
        <button
          onClick={() => setConds(p => [...p, defaultCond()])}
          className="text-xs text-blue-400 hover:text-blue-300 border border-blue-800 rounded-lg px-2.5 py-1 transition-colors"
        >+ 添加条件</button>
      </div>
      {conds.length === 0 ? (
        <div className="text-xs text-gray-600 bg-gray-800/30 rounded-lg p-3 text-center">{emptyHint}</div>
      ) : (
        conds.map((c, i) => (
          <ConditionRow
            key={i}
            cond={c}
            onChange={nc => setConds(p => p.map((x, j) => j === i ? nc : x))}
            onDelete={() => setConds(p => p.filter((_, j) => j !== i))}
          />
        ))
      )}
      {conds.length > 1 && <p className="text-xs text-gray-600">↑ 以上条件同时满足（AND）</p>}
    </div>
  )

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-5">
      {/* Name + desc */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">策略名称 *</label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="给策略起个名字..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">描述（可选）</label>
          <input
            value={desc}
            onChange={e => setDesc(e.target.value)}
            placeholder="一句话描述策略思路..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none focus:border-blue-500"
          />
        </div>
      </div>

      {/* Mode tabs */}
      <div className="flex gap-2 items-center">
        <button
          onClick={() => setMode('visual')}
          className={`text-sm px-4 py-2 rounded-lg font-medium transition-colors ${mode === 'visual' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
        >🎛️ 可视化</button>
        <button
          onClick={switchToCode}
          className={`text-sm px-4 py-2 rounded-lg font-medium transition-colors ${mode === 'code' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
        >💻 代码</button>
        <span className="text-xs text-gray-600 hidden sm:inline">
          {mode === 'visual' ? '点击「代码」可查看 / 编辑自动生成的 JS 函数' : '函数名必须为 strategy，返回信号数组'}
        </span>
      </div>

      {mode === 'visual' ? (
        <>
          {condSection('📈 买入条件', 'text-emerald-400', buyConds, setBuyConds, '暂无买入条件，点击右侧「添加条件」')}
          <hr className="border-gray-800" />
          {condSection('📉 卖出条件', 'text-red-400', sellConds, setSellConds, '暂无卖出条件（将一直持仓至回测结束）')}
        </>
      ) : (
        <div className="space-y-1.5">
          <p className="text-xs text-gray-500">
            💡 可直接编辑代码，保存时会自动验证。可用指标：
            <code className="bg-gray-800 px-1 rounded mx-1 text-green-300">calcMA(arr, n)</code>
            <code className="bg-gray-800 px-1 rounded mx-1 text-green-300">calcRSI(arr, n)</code>
            <code className="bg-gray-800 px-1 rounded mx-1 text-green-300">calcBB(arr, n, m)</code>
          </p>
          <textarea
            value={code}
            onChange={e => setCode(e.target.value)}
            spellCheck={false}
            className="w-full h-72 bg-gray-950 border border-gray-700 rounded-xl p-4 text-xs text-green-300 font-mono outline-none focus:border-blue-500 resize-none leading-relaxed"
          />
        </div>
      )}

      {error && (
        <div className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">{error}</div>
      )}

      <div className="flex gap-2 pt-1">
        <button onClick={handleSave} className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-5 py-2 rounded-lg font-medium transition-colors">
          保存策略
        </button>
        <button onClick={onCancel} className="bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm px-5 py-2 rounded-lg transition-colors">
          取消
        </button>
      </div>
    </div>
  )
}

// ── BacktestRunner ────────────────────────────────────────────────────────────

function BacktestRunner({ strategy }: { strategy: CustomStrategy }) {
  const [symbol,    setSymbol]    = useState('')
  const [range,     setRange]     = useState<DateRange>('1y')
  const [triggered, setTriggered] = useState(false)
  const [runSymbol, setRunSymbol] = useState('')
  const [runRange,  setRunRange]  = useState<DateRange>('1y')
  const [result,    setResult]    = useState<BacktestResult | null>(null)
  const [runError,  setRunError]  = useState('')

  const { start, end } = getDateRange(runRange)

  const { data, isLoading, isError, error } = useQuery<OhlcvResponse>({
    queryKey: ['custom-bt', strategy.id, runSymbol, runRange],
    queryFn: async () => {
      const res = await fetch(`/api/review/${runSymbol}?start=${start}&end=${end}`)
      if (!res.ok) throw new Error('K线数据获取失败')
      return res.json()
    },
    enabled: triggered && runSymbol !== '',
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (!data?.ohlcv?.length) return
    try {
      setResult(runCustomBacktest(data.ohlcv, strategy.code))
      setRunError('')
    } catch (e) { setRunError(String(e)); setResult(null) }
  }, [data, strategy.code])

  const handleRun = () => {
    if (!symbol.trim()) return
    setRunSymbol(symbol.trim())
    setRunRange(range)
    setTriggered(true)
    setResult(null)
  }

  const retColor = (v: number) => v > 0 ? 'text-red-400' : v < 0 ? 'text-emerald-400' : 'text-gray-400'

  const RANGES: { key: DateRange; label: string }[] = [
    { key: '3m', label: '近3月' },
    { key: '6m', label: '近6月' },
    { key: '1y', label: '近1年' },
  ]

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4 mt-1">
      <p className="text-sm font-medium text-gray-300">
        📊 运行回测：<span className="text-blue-400">{strategy.name}</span>
      </p>

      <div className="flex gap-2 flex-wrap items-start">
        <div className="flex-1 min-w-0">
          <StockSearch
            value={symbol}
            onChange={(sym, _name) => setSymbol(sym)}
            placeholder="代码 / 名称 / 拼音缩写，如 600519 / 茅台 / gzmg"
          />
        </div>
        {RANGES.map(r => (
          <button key={r.key} onClick={() => setRange(r.key)}
            className={`text-xs px-3 py-2 rounded-lg transition-colors ${range === r.key ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}>
            {r.label}
          </button>
        ))}
        <button
          onClick={handleRun}
          disabled={!symbol.trim()}
          className="text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-lg px-4 py-2 font-medium transition-colors"
        >运行</button>
      </div>

      {triggered && isLoading && (
        <div className="flex items-center gap-2 text-gray-500 text-sm">
          <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          正在加载 {runSymbol} K线…
        </div>
      )}
      {triggered && isError && <p className="text-red-400 text-sm">{(error as Error).message}</p>}
      {runError && (
        <div className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg p-3">⚠️ {runError}</div>
      )}

      {result && (
        <div className="space-y-4">
          <p className="text-xs text-gray-600">{runSymbol} · {start}~{end} · {data?.ohlcv.length} 个交易日</p>

          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={result.equity} margin={{ top: 4, right: 20, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="date" tick={{ fill: '#4b5563', fontSize: 9 }} tickFormatter={v => v.slice(5)} interval="preserveStartEnd" />
              <YAxis tick={{ fill: '#4b5563', fontSize: 9 }} domain={['auto', 'auto']} width={36} tickFormatter={v => v.toFixed(0)} />
              <Tooltip
                contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 11 }}
                formatter={(v: unknown, n: unknown) => [(v as number).toFixed(2), n as string]}
              />
              <Legend iconType="line" wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="value"    name={strategy.name} stroke="#3b82f6" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="baseline" name="买入持有"       stroke="#6b7280" dot={false} strokeWidth={1} strokeDasharray="4 2" />
            </LineChart>
          </ResponsiveContainer>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[
              { label: '总收益',    value: `${result.totalReturn > 0 ? '+' : ''}${result.totalReturn}%`,  color: retColor(result.totalReturn) },
              { label: '最大回撤',  value: `-${result.maxDrawdown}%`,                                      color: 'text-yellow-500' },
              { label: '胜率',      value: `${result.winRate}%`,                                           color: 'text-gray-300' },
              { label: '交易次数',  value: String(result.trades),                                          color: 'text-gray-300' },
              { label: 'Sharpe',   value: String(result.sharpe),                                           color: result.sharpe >= 0 ? 'text-red-400' : 'text-emerald-400' },
              { label: 'vs 买入持有', value: `${result.vsBaseline > 0 ? '+' : ''}${result.vsBaseline}%`, color: retColor(result.vsBaseline) },
            ].map(s => (
              <div key={s.label} className="bg-gray-800/50 rounded-xl p-3 text-center">
                <div className="text-xs text-gray-500 mb-1">{s.label}</div>
                <div className={`text-lg font-bold ${s.color}`}>{s.value}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
}

export default function CustomStrategyPage({ onSelectStock: _onSelectStock }: Props) {
  const [strategies, setStrategies] = useState<CustomStrategy[]>(() => loadStrategies())
  const [editing,    setEditing]    = useState<CustomStrategy | null | 'new'>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const selectedStrategy = strategies.find(s => s.id === selectedId) ?? null

  function handleSave(s: CustomStrategy) {
    setStrategies(prev => {
      const next = prev.some(x => x.id === s.id)
        ? prev.map(x => x.id === s.id ? s : x)
        : [...prev, s]
      saveStrategies(next)
      return next
    })
    setEditing(null)
    setSelectedId(s.id)
  }

  function handleDelete(id: string) {
    if (!window.confirm('确认删除这个策略？')) return
    setStrategies(prev => { const next = prev.filter(x => x.id !== id); saveStrategies(next); return next })
    if (selectedId === id) setSelectedId(null)
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">我的策略</h2>
          <p className="text-xs text-gray-500 mt-0.5">可视化配置买卖规则，自动生成代码，支持手动修改</p>
        </div>
        {editing === null && (
          <button
            onClick={() => { setEditing('new'); setSelectedId(null) }}
            className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg font-medium transition-colors"
          >+ 新建策略</button>
        )}
      </div>

      {/* Editor */}
      {editing !== null && (
        <StrategyEditor
          initial={editing === 'new' ? undefined : editing}
          onSave={handleSave}
          onCancel={() => setEditing(null)}
        />
      )}

      {editing === null && (
        <>
          {strategies.length === 0 ? (
            <div className="bg-gray-900 border border-gray-800 border-dashed rounded-xl p-12 text-center space-y-3">
              <div className="text-4xl">✏️</div>
              <div className="text-gray-400 font-medium">还没有自定义策略</div>
              <div className="text-xs text-gray-600">
                点击「新建策略」，用可视化方式配置买卖条件<br />
                支持 MA均线、RSI、布林带等指标，无需写代码
              </div>
              <button
                onClick={() => setEditing('new')}
                className="mt-2 text-sm bg-blue-600 hover:bg-blue-500 text-white px-5 py-2 rounded-lg font-medium transition-colors"
              >+ 新建我的第一个策略</button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {strategies.map(s => (
                <div
                  key={s.id}
                  onClick={() => setSelectedId(prev => prev === s.id ? null : s.id)}
                  className={`cursor-pointer p-4 rounded-xl border transition-all ${
                    selectedId === s.id
                      ? 'bg-blue-900/20 border-blue-600 shadow-lg shadow-blue-900/20'
                      : 'bg-gray-900 border-gray-800 hover:border-gray-600'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <span className="font-semibold text-white text-sm truncate">{s.name}</span>
                    <span className="text-xs text-gray-600 shrink-0 bg-gray-800 px-1.5 py-0.5 rounded">
                      {s.mode === 'visual' ? '🎛️' : '💻'}
                    </span>
                  </div>
                  {s.desc && <p className="text-xs text-gray-500 mb-2 line-clamp-2">{s.desc}</p>}
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-xs text-gray-700">
                      {new Date(s.createdAt).toLocaleDateString('zh-CN')}
                    </span>
                    <div className="flex gap-3" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => setEditing(s)}
                        className="text-xs text-gray-500 hover:text-blue-400 transition-colors"
                      >编辑</button>
                      <button
                        onClick={() => handleDelete(s.id)}
                        className="text-xs text-gray-500 hover:text-red-400 transition-colors"
                      >删除</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {selectedStrategy && <BacktestRunner key={selectedStrategy.id} strategy={selectedStrategy} />}
        </>
      )}
    </div>
  )
}
