import type { OhlcvBar } from '../types'

export interface StrategyResult {
  name: string
  color: string
  equity: { date: string; value: number }[]
  totalReturn: number       // %
  maxDrawdown: number       // %（负值）
  winRate: number           // %
  trades: number
  sharpe: number
}

export interface MonthlyReturn {
  month: string             // "2025-03"
  returns: Record<string, number>  // strategyName -> %
}

/** 计算最大回撤 */
function calcMaxDrawdown(equity: number[]): number {
  let peak = equity[0]
  let maxDD = 0
  for (const v of equity) {
    if (v > peak) peak = v
    const dd = (v - peak) / peak * 100
    if (dd < maxDD) maxDD = dd
  }
  return maxDD
}

/** 计算日收益率序列的 Sharpe（年化，无风险利率2.5%） */
function calcSharpe(equity: number[]): number {
  if (equity.length < 2) return 0
  const dailyReturns: number[] = []
  for (let i = 1; i < equity.length; i++) {
    dailyReturns.push((equity[i] - equity[i - 1]) / equity[i - 1])
  }
  const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length
  const variance = dailyReturns.reduce((a, b) => a + (b - mean) ** 2, 0) / dailyReturns.length
  const std = Math.sqrt(variance)
  if (std === 0) return 0
  const annualMean = mean * 252 - 0.025
  return parseFloat((annualMean / (std * Math.sqrt(252))).toFixed(2))
}

/**
 * 策略1：买入持有
 * 首日买入，末日卖出
 */
export function strategyBuyHold(ohlcv: OhlcvBar[]): StrategyResult {
  const base = ohlcv[0].close
  const equity: { date: string; value: number }[] = ohlcv.map(bar => ({
    date: String(bar.date).slice(0, 10),
    value: parseFloat(((bar.close / base) * 100).toFixed(2)),
  }))
  const values = equity.map(e => e.value)
  const totalReturn = parseFloat(((values[values.length - 1] - 100)).toFixed(2))
  return {
    name: '买入持有',
    color: '#6366f1',
    equity,
    totalReturn,
    maxDrawdown: parseFloat(calcMaxDrawdown(values).toFixed(2)),
    winRate: 0,
    trades: 1,
    sharpe: calcSharpe(values),
  }
}

/**
 * 策略2：MA双均线（快线=ma5, 慢线=ma20）
 * 金叉买入，死叉卖出
 */
export function strategyMACross(ohlcv: OhlcvBar[]): StrategyResult {
  let position = 0  // 0=空仓, 1=持仓
  let costPrice = 0
  let cash = 100.0
  let holdings = 0.0
  const equity: { date: string; value: number }[] = []
  let wins = 0, losses = 0, trades = 0

  for (let i = 0; i < ohlcv.length; i++) {
    const bar = ohlcv[i]
    const ma5  = bar.ma5  as number | null
    const ma20 = bar.ma20 as number | null
    const prevMa5  = i > 0 ? (ohlcv[i - 1].ma5  as number | null) : null
    const prevMa20 = i > 0 ? (ohlcv[i - 1].ma20 as number | null) : null

    // 金叉：上穿买入
    if (
      position === 0 && ma5 != null && ma20 != null &&
      prevMa5 != null && prevMa20 != null &&
      prevMa5 <= prevMa20 && ma5 > ma20 && cash > 0
    ) {
      holdings = cash / bar.close
      costPrice = bar.close
      cash = 0
      position = 1
      trades++
    }
    // 死叉：下穿卖出
    else if (
      position === 1 && ma5 != null && ma20 != null &&
      prevMa5 != null && prevMa20 != null &&
      prevMa5 >= prevMa20 && ma5 < ma20
    ) {
      cash = holdings * bar.close
      if (bar.close > costPrice) wins++; else losses++
      holdings = 0
      position = 0
    }

    const totalValue = cash + holdings * bar.close
    equity.push({ date: String(bar.date).slice(0, 10), value: parseFloat(totalValue.toFixed(2)) })
  }

  const values = equity.map(e => e.value)
  const totalReturn = parseFloat((values[values.length - 1] - 100).toFixed(2))
  const winRate = trades > 0 ? parseFloat(((wins / Math.max(wins + losses, 1)) * 100).toFixed(1)) : 0

  return {
    name: 'MA5/20金叉',
    color: '#f59e0b',
    equity,
    totalReturn,
    maxDrawdown: parseFloat(calcMaxDrawdown(values).toFixed(2)),
    winRate,
    trades,
    sharpe: calcSharpe(values),
  }
}

/**
 * 策略3：RSI反转
 * RSI < 35 买入，RSI > 65 卖出
 */
export function strategyRsiReversal(ohlcv: OhlcvBar[], buyThresh = 35, sellThresh = 65): StrategyResult {
  // 先从 OHLCV 里取 close 重新算 RSI14（bar.rsi14 不在接口里，需要自行算）
  const closes = ohlcv.map(b => b.close as number)
  const rsi14 = calcRsi(closes, 14)

  let position = 0
  let cash = 100.0
  let holdings = 0.0
  let costPrice = 0
  let wins = 0, losses = 0, trades = 0
  const equity: { date: string; value: number }[] = []

  for (let i = 0; i < ohlcv.length; i++) {
    const bar = ohlcv[i]
    const rsi = rsi14[i]

    if (position === 0 && rsi != null && rsi < buyThresh && cash > 0) {
      holdings = cash / bar.close
      costPrice = bar.close
      cash = 0
      position = 1
      trades++
    } else if (position === 1 && rsi != null && rsi > sellThresh) {
      cash = holdings * bar.close
      if (bar.close > costPrice) wins++; else losses++
      holdings = 0
      position = 0
    }

    const totalValue = cash + holdings * bar.close
    equity.push({ date: String(bar.date).slice(0, 10), value: parseFloat(totalValue.toFixed(2)) })
  }

  const values = equity.map(e => e.value)
  const totalReturn = parseFloat((values[values.length - 1] - 100).toFixed(2))
  const winRate = trades > 0 ? parseFloat(((wins / Math.max(wins + losses, 1)) * 100).toFixed(1)) : 0

  return {
    name: 'RSI反转',
    color: '#10b981',
    equity,
    totalReturn,
    maxDrawdown: parseFloat(calcMaxDrawdown(values).toFixed(2)),
    winRate,
    trades,
    sharpe: calcSharpe(values),
  }
}

/** 计算 RSI，返回与输入等长的数组（前 period-1 个为 null） */
function calcRsi(closes: number[], period = 14): (number | null)[] {
  const result: (number | null)[] = Array(closes.length).fill(null)
  if (closes.length <= period) return result

  const gains: number[] = []
  const losses: number[] = []
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1]
    gains.push(Math.max(diff, 0))
    losses.push(Math.max(-diff, 0))
  }

  let avgGain = gains.reduce((a, b) => a + b, 0) / period
  let avgLoss = losses.reduce((a, b) => a + b, 0) / period

  result[period] = avgLoss === 0 ? 100 : parseFloat((100 - 100 / (1 + avgGain / avgLoss)).toFixed(2))

  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1]
    avgGain = (avgGain * (period - 1) + Math.max(diff, 0)) / period
    avgLoss = (avgLoss * (period - 1) + Math.max(-diff, 0)) / period
    result[i] = avgLoss === 0 ? 100 : parseFloat((100 - 100 / (1 + avgGain / avgLoss)).toFixed(2))
  }
  return result
}

/** 计算简单移动平均，返回与输入等长数组（前 period-1 个为 null） */
export function calcSMA(values: number[], period: number): (number | null)[] {
  const result: (number | null)[] = Array(values.length).fill(null)
  for (let i = period - 1; i < values.length; i++) {
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += values[j]
    result[i] = sum / period
  }
  return result
}

/** 计算 EMA，返回与输入等长数组（前 period-1 个为 null） */
function calcEMA(values: number[], period: number): (number | null)[] {
  const result: (number | null)[] = Array(values.length).fill(null)
  if (values.length < period) return result
  const k = 2 / (period + 1)
  let ema = values.slice(0, period).reduce((a, b) => a + b, 0) / period
  result[period - 1] = ema
  for (let i = period; i < values.length; i++) {
    ema = values[i] * k + ema * (1 - k)
    result[i] = ema
  }
  return result
}

/**
 * 策略4：布林带
 * 收盘价跌破下轨 → 买入；收盘价突破上轨 → 卖出
 */
export function strategyBollingerBands(ohlcv: OhlcvBar[], period = 20, stdMult = 2): StrategyResult {
  if (ohlcv.length < period + 1) {
    return { name: '布林带', color: '#8b5cf6', equity: [], totalReturn: 0, maxDrawdown: 0, winRate: 0, trades: 0, sharpe: 0 }
  }

  const closes = ohlcv.map(b => b.close)
  const sma = calcSMA(closes, period)

  // 计算标准差和上下轨
  const upper: (number | null)[] = Array(closes.length).fill(null)
  const lower: (number | null)[] = Array(closes.length).fill(null)
  for (let i = period - 1; i < closes.length; i++) {
    const mid = sma[i] as number
    let variance = 0
    for (let j = i - period + 1; j <= i; j++) variance += (closes[j] - mid) ** 2
    const std = Math.sqrt(variance / period)
    upper[i] = mid + stdMult * std
    lower[i] = mid - stdMult * std
  }

  let position = 0
  let cash = 100.0
  let holdings = 0.0
  let costPrice = 0
  let wins = 0, losses = 0, trades = 0
  const equity: { date: string; value: number }[] = []

  for (let i = 0; i < ohlcv.length; i++) {
    const bar = ohlcv[i]
    const lo = lower[i]
    const up = upper[i]

    if (lo != null && up != null) {
      if (position === 0 && bar.close < lo && cash > 0) {
        holdings = cash / bar.close
        costPrice = bar.close
        cash = 0
        position = 1
        trades++
      } else if (position === 1 && bar.close > up) {
        cash = holdings * bar.close
        if (bar.close > costPrice) wins++; else losses++
        holdings = 0
        position = 0
      }
    }

    const totalValue = cash + holdings * bar.close
    equity.push({ date: String(bar.date).slice(0, 10), value: parseFloat(totalValue.toFixed(2)) })
  }

  const values = equity.map(e => e.value)
  const totalReturn = parseFloat((values[values.length - 1] - 100).toFixed(2))
  const winRate = trades > 0 ? parseFloat(((wins / Math.max(wins + losses, 1)) * 100).toFixed(1)) : 0

  return {
    name: '布林带',
    color: '#8b5cf6',
    equity,
    totalReturn,
    maxDrawdown: parseFloat(calcMaxDrawdown(values).toFixed(2)),
    winRate,
    trades,
    sharpe: calcSharpe(values),
  }
}

/**
 * 策略5：MACD金叉
 * 柱状图由负转正（快线上穿慢线）→ 买入；由正转负 → 卖出
 */
export function strategyMACD(ohlcv: OhlcvBar[], fast = 12, slow = 26, signal = 9): StrategyResult {
  if (ohlcv.length < slow + signal + 1) {
    return { name: 'MACD金叉', color: '#ec4899', equity: [], totalReturn: 0, maxDrawdown: 0, winRate: 0, trades: 0, sharpe: 0 }
  }

  const closes = ohlcv.map(b => b.close)
  const emaFast = calcEMA(closes, fast)
  const emaSlow = calcEMA(closes, slow)

  // MACD line = fast EMA - slow EMA
  const macdLine: (number | null)[] = closes.map((_, i) => {
    if (emaFast[i] == null || emaSlow[i] == null) return null
    return (emaFast[i] as number) - (emaSlow[i] as number)
  })

  // Signal line = EMA of MACD line (only non-null values)
  const macdNonNull = macdLine.filter(v => v != null) as number[]
  const signalEmaRaw = calcEMA(macdNonNull, signal)

  // Re-align signal to original indices
  const signalLine: (number | null)[] = Array(closes.length).fill(null)
  let nonNullIdx = 0
  for (let i = 0; i < closes.length; i++) {
    if (macdLine[i] != null) {
      signalLine[i] = signalEmaRaw[nonNullIdx]
      nonNullIdx++
    }
  }

  // Histogram = MACD - Signal
  const histogram: (number | null)[] = closes.map((_, i) => {
    if (macdLine[i] == null || signalLine[i] == null) return null
    return (macdLine[i] as number) - (signalLine[i] as number)
  })

  let position = 0
  let cash = 100.0
  let holdings = 0.0
  let costPrice = 0
  let wins = 0, losses = 0, trades = 0
  const equity: { date: string; value: number }[] = []

  for (let i = 1; i < ohlcv.length; i++) {
    const bar = ohlcv[i]
    const hist = histogram[i]
    const prevHist = histogram[i - 1]

    if (hist != null && prevHist != null) {
      // 柱子由负转正：买入
      if (position === 0 && prevHist <= 0 && hist > 0 && cash > 0) {
        holdings = cash / bar.close
        costPrice = bar.close
        cash = 0
        position = 1
        trades++
      }
      // 柱子由正转负：卖出
      else if (position === 1 && prevHist >= 0 && hist < 0) {
        cash = holdings * bar.close
        if (bar.close > costPrice) wins++; else losses++
        holdings = 0
        position = 0
      }
    }

    const totalValue = cash + holdings * bar.close
    equity.push({ date: String(bar.date).slice(0, 10), value: parseFloat(totalValue.toFixed(2)) })
  }

  // Prepend first bar (no signal possible on day 0)
  equity.unshift({ date: String(ohlcv[0].date).slice(0, 10), value: 100 })

  const values = equity.map(e => e.value)
  const totalReturn = parseFloat((values[values.length - 1] - 100).toFixed(2))
  const winRate = trades > 0 ? parseFloat(((wins / Math.max(wins + losses, 1)) * 100).toFixed(1)) : 0

  return {
    name: 'MACD金叉',
    color: '#ec4899',
    equity,
    totalReturn,
    maxDrawdown: parseFloat(calcMaxDrawdown(values).toFixed(2)),
    winRate,
    trades,
    sharpe: calcSharpe(values),
  }
}

/**
 * 策略6：价格突破
 * 收盘价 > 近N日最高价 → 买入；收盘价 < 近N日最低价 → 卖出
 */
export function strategyBreakout(ohlcv: OhlcvBar[], lookback = 20): StrategyResult {
  if (ohlcv.length < lookback + 1) {
    return { name: '价格突破', color: '#f97316', equity: [], totalReturn: 0, maxDrawdown: 0, winRate: 0, trades: 0, sharpe: 0 }
  }

  let position = 0
  let cash = 100.0
  let holdings = 0.0
  let costPrice = 0
  let wins = 0, losses = 0, trades = 0
  const equity: { date: string; value: number }[] = []

  for (let i = 0; i < ohlcv.length; i++) {
    const bar = ohlcv[i]

    if (i >= lookback) {
      // 近lookback日（不含当天）的最高价和最低价
      const prevBars = ohlcv.slice(i - lookback, i)
      const prevHigh = Math.max(...prevBars.map(b => b.high))
      const prevLow  = Math.min(...prevBars.map(b => b.low))

      if (position === 0 && bar.close > prevHigh && cash > 0) {
        holdings = cash / bar.close
        costPrice = bar.close
        cash = 0
        position = 1
        trades++
      } else if (position === 1 && bar.close < prevLow) {
        cash = holdings * bar.close
        if (bar.close > costPrice) wins++; else losses++
        holdings = 0
        position = 0
      }
    }

    const totalValue = cash + holdings * bar.close
    equity.push({ date: String(bar.date).slice(0, 10), value: parseFloat(totalValue.toFixed(2)) })
  }

  const values = equity.map(e => e.value)
  const totalReturn = parseFloat((values[values.length - 1] - 100).toFixed(2))
  const winRate = trades > 0 ? parseFloat(((wins / Math.max(wins + losses, 1)) * 100).toFixed(1)) : 0

  return {
    name: '价格突破',
    color: '#f97316',
    equity,
    totalReturn,
    maxDrawdown: parseFloat(calcMaxDrawdown(values).toFixed(2)),
    winRate,
    trades,
    sharpe: calcSharpe(values),
  }
}

/** 计算月度收益 */
export function calcMonthlyReturns(strategies: StrategyResult[]): MonthlyReturn[] {
  if (!strategies.length || !strategies[0].equity.length) return []

  // 按月分组
  const months = new Map<string, Map<string, { start: number; end: number }>>()

  for (const strat of strategies) {
    for (const point of strat.equity) {
      const month = point.date.slice(0, 7)
      if (!months.has(month)) months.set(month, new Map())
      const m = months.get(month)!
      if (!m.has(strat.name)) {
        m.set(strat.name, { start: point.value, end: point.value })
      } else {
        m.get(strat.name)!.end = point.value
      }
    }
  }

  return Array.from(months.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, stratMap]) => ({
      month,
      returns: Object.fromEntries(
        Array.from(stratMap.entries()).map(([name, { start, end }]) => [
          name,
          parseFloat(((end - start) / start * 100).toFixed(2)),
        ])
      ),
    }))
}
