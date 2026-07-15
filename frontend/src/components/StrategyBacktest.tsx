import { useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, BarChart, Bar, Cell, Legend,
} from 'recharts'
import type { OhlcvBar } from '../types'
import {
  strategyBuyHold, strategyMACross, strategyRsiReversal,
  calcMonthlyReturns, type StrategyResult,
} from '../utils/backtest'

interface Props {
  ohlcv: OhlcvBar[]
}

function MetricCard({
  label, value, sub, positive,
}: {
  label: string
  value: string
  sub?: string
  positive?: boolean | null
}) {
  const color =
    positive === true ? 'text-red-400' :
    positive === false ? 'text-emerald-400' :
    'text-gray-200'
  return (
    <div className="bg-gray-800/60 rounded-lg p-3 text-center">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-lg font-bold tabular-nums ${color}`}>{value}</div>
      {sub && <div className="text-xs text-gray-600 mt-0.5">{sub}</div>}
    </div>
  )
}

function StrategyRow({ s }: { s: StrategyResult }) {
  const retColor = s.totalReturn > 0 ? 'text-red-400' : s.totalReturn < 0 ? 'text-emerald-400' : 'text-gray-400'
  const ddColor  = s.maxDrawdown < -15 ? 'text-red-400' : s.maxDrawdown < -8 ? 'text-orange-400' : 'text-gray-400'
  return (
    <tr className="border-t border-gray-800 text-xs">
      <td className="py-2 pr-3">
        <span className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: s.color }} />
          <span className="text-gray-300">{s.name}</span>
        </span>
      </td>
      <td className={`py-2 pr-3 text-right font-mono ${retColor}`}>
        {s.totalReturn > 0 ? '+' : ''}{s.totalReturn}%
      </td>
      <td className={`py-2 pr-3 text-right font-mono ${ddColor}`}>{s.maxDrawdown}%</td>
      <td className="py-2 pr-3 text-right font-mono text-gray-400">{s.winRate > 0 ? s.winRate + '%' : '--'}</td>
      <td className="py-2 pr-3 text-right font-mono text-gray-400">{s.trades}</td>
      <td className="py-2 text-right font-mono text-gray-400">{s.sharpe}</td>
    </tr>
  )
}

const TICK_STYLE = { fill: '#6b7280', fontSize: 10 }

export default function StrategyBacktest({ ohlcv }: Props) {
  const strategies = useMemo<StrategyResult[]>(() => {
    if (!ohlcv || ohlcv.length < 5) return []
    return [
      strategyBuyHold(ohlcv),
      strategyMACross(ohlcv),
      strategyRsiReversal(ohlcv),
    ]
  }, [ohlcv])

  const monthly = useMemo(() => calcMonthlyReturns(strategies), [strategies])

  if (!strategies.length) return null

  // 合并权益曲线数据（by date）
  const equityData = strategies[0].equity.map((pt, i) => {
    const row: Record<string, string | number> = { date: pt.date.slice(5) }
    for (const s of strategies) {
      row[s.name] = s.equity[i]?.value ?? 100
    }
    return row
  })

  // x轴抽样（最多12个刻度）
  const tickCount = Math.min(12, equityData.length)
  const step = Math.floor(equityData.length / tickCount)
  const ticks = equityData
    .filter((_, i) => i % step === 0 || i === equityData.length - 1)
    .map(d => d.date)

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-5">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-gray-300">📈 策略回测对比</span>
        <span className="text-xs text-gray-600">基于区间K线，初始资金 100 单位，不含手续费</span>
      </div>

      {/* 权益曲线 */}
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={equityData} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="date" ticks={ticks} tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={v => `${v}`} domain={['auto', 'auto']} />
          <ReferenceLine y={100} stroke="#374151" strokeDasharray="4 2" />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#9ca3af' }}
            formatter={(value, name) => {
              const v = Number(value ?? 0)
              return [`${v > 100 ? '+' : ''}${(v - 100).toFixed(2)}%`, String(name)] as [string, string]
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
            formatter={v => <span style={{ color: '#9ca3af' }}>{v}</span>}
          />
          {strategies.map(s => (
            <Line
              key={s.name}
              type="monotone"
              dataKey={s.name}
              stroke={s.color}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>

      {/* 策略指标对比表 */}
      <div className="overflow-x-auto">
        <table className="w-full text-right">
          <thead>
            <tr className="text-xs text-gray-600">
              <th className="text-left pb-2 pr-3">策略</th>
              <th className="pb-2 pr-3">总收益</th>
              <th className="pb-2 pr-3">最大回撤</th>
              <th className="pb-2 pr-3">胜率</th>
              <th className="pb-2 pr-3">交易次数</th>
              <th className="pb-2">Sharpe</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map(s => <StrategyRow key={s.name} s={s} />)}
          </tbody>
        </table>
      </div>

      {/* 月度收益柱状图 */}
      {monthly.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 mb-2">月度收益 (%)</div>
          <ResponsiveContainer width="100%" height={120}>
            <BarChart data={monthly} margin={{ top: 0, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
              <XAxis dataKey="month" tick={{ ...TICK_STYLE, fontSize: 9 }} tickFormatter={v => v.slice(5)} />
              <YAxis tick={TICK_STYLE} tickFormatter={v => `${v}%`} />
              <Tooltip
                contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 11 }}
                formatter={(value) => {
                  const v = Number(value ?? 0)
                  return [`${v > 0 ? '+' : ''}${v}%`, '收益'] as [string, string]
                }}
              />
              {strategies.map(s => (
                <Bar key={s.name} dataKey={`returns.${s.name}`} name={s.name} fill={s.color} radius={[2, 2, 0, 0]}>
                  {monthly.map((m, i) => (
                    <Cell
                      key={i}
                      fill={
                        (m.returns[s.name] ?? 0) >= 0
                          ? s.color
                          : s.color + '88'
                      }
                    />
                  ))}
                </Bar>
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 信号说明 */}
      <div className="grid grid-cols-3 gap-2 pt-1 border-t border-gray-800">
        {strategies.map(s => (
          <MetricCard
            key={s.name}
            label={s.name}
            value={`${s.totalReturn > 0 ? '+' : ''}${s.totalReturn}%`}
            sub={`回撤 ${s.maxDrawdown}%`}
            positive={s.totalReturn > 0 ? true : s.totalReturn < 0 ? false : null}
          />
        ))}
      </div>

      <p className="text-xs text-gray-700 pt-1">
        ⚠ 回测结果基于历史数据，不代表未来收益。MA金叉/死叉使用已有ma5/ma20数据，RSI反转阈值 35/65。
      </p>
    </div>
  )
}
