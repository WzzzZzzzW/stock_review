import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import type { ReviewVerdict } from '../types'

const GRADE_COLOR: Record<string, string> = {
  A: 'bg-emerald-700 text-white',
  B: 'bg-blue-700 text-white',
  C: 'bg-yellow-600 text-white',
  D: 'bg-orange-700 text-white',
  F: 'bg-red-800 text-white',
}

function pctColor(v?: number | null) {
  if (v == null) return 'text-gray-400'
  return v > 0 ? 'text-red-400' : v < 0 ? 'text-emerald-400' : 'text-gray-400'
}

function RelativeChart({ rel }: { rel: NonNullable<ReviewVerdict['relative']> }) {
  const series = rel.series ?? []
  if (series.length < 2) return null
  return (
    <div className="h-28 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
          <XAxis dataKey="date" hide />
          <YAxis domain={['dataMin - 2', 'dataMax + 2']} tick={{ fontSize: 9, fill: '#6b7280' }} width={34} />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: '#9ca3af' }}
            formatter={(v: any, n: any) => [`${Number(v).toFixed(1)}`, n === 'stock' ? '个股' : (rel.index_name ?? '大盘')]}
          />
          <ReferenceLine y={100} stroke="#374151" strokeDasharray="3 3" />
          <Line type="monotone" dataKey="index" stroke="#9ca3af" strokeWidth={1.4} dot={false} name="index" />
          <Line type="monotone" dataKey="stock" stroke="#f87171" strokeWidth={2} dot={false} name="stock" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function ReviewVerdictCard({ verdict }: { verdict: ReviewVerdict }) {
  if (!verdict || !verdict.stance) return null
  const pos = verdict.position ?? {}
  const rel = verdict.relative
  const val = verdict.valuation
  const grade = verdict.grade ?? 'C'
  const gradeCls = GRADE_COLOR[grade] ?? GRADE_COLOR.C
  const bullRatio = verdict.bull_ratio ?? 50

  return (
    <div className="bg-gradient-to-br from-gray-900 to-gray-900/40 border border-gray-700 rounded-2xl p-5 space-y-4">
      {/* 顶行：一句话判断 + 评级 */}
      <div className="flex items-start gap-3">
        <span className="text-lg shrink-0">🧭</span>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-gray-400">复盘速览</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${gradeCls}`}>财务 {grade} 级</span>
            {verdict.trend && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                verdict.trend === '上行' ? 'border-red-700 text-red-300' :
                verdict.trend === '下行' ? 'border-emerald-700 text-emerald-300' :
                'border-gray-600 text-gray-400'
              }`}>趋势{verdict.trend}</span>
            )}
          </div>
          <p className="text-[15px] font-semibold text-white leading-snug">{verdict.stance}</p>
        </div>
      </div>

      {/* 标签 chips */}
      {(verdict.tags ?? []).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {verdict.tags!.map((t, i) => (
            <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-gray-800 border border-gray-700 text-gray-300">{t}</span>
          ))}
        </div>
      )}

      {/* 多空力量条 */}
      <div>
        <div className="flex items-center justify-between text-[11px] mb-1">
          <span className="text-red-400 font-medium">多 {(verdict.bull_points ?? []).length}</span>
          <span className="text-gray-500">多空力量 {bullRatio}%</span>
          <span className="text-emerald-400 font-medium">空 {(verdict.bear_points ?? []).length}</span>
        </div>
        <div className="h-2 rounded-full overflow-hidden flex bg-gray-800">
          <div className="bg-red-500/70 h-full" style={{ width: `${bullRatio}%` }} />
          <div className="bg-emerald-500/70 h-full" style={{ width: `${100 - bullRatio}%` }} />
        </div>
      </div>

      {/* 多空要点两栏 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="bg-red-900/10 border border-red-900/40 rounded-lg p-3">
          <p className="text-[11px] font-semibold text-red-400 mb-1.5">📈 看多依据</p>
          <ul className="space-y-1">
            {(verdict.bull_points ?? []).length === 0 && <li className="text-xs text-gray-600">暂无明显看多信号</li>}
            {(verdict.bull_points ?? []).map((p, i) => (
              <li key={i} className="text-xs text-gray-300 flex gap-1.5"><span className="text-red-500 shrink-0">·</span>{p}</li>
            ))}
          </ul>
        </div>
        <div className="bg-emerald-900/10 border border-emerald-900/40 rounded-lg p-3">
          <p className="text-[11px] font-semibold text-emerald-400 mb-1.5">📉 看空依据</p>
          <ul className="space-y-1">
            {(verdict.bear_points ?? []).length === 0 && <li className="text-xs text-gray-600">暂无明显看空信号</li>}
            {(verdict.bear_points ?? []).map((p, i) => (
              <li key={i} className="text-xs text-gray-300 flex gap-1.5"><span className="text-emerald-500 shrink-0">·</span>{p}</li>
            ))}
          </ul>
        </div>
      </div>

      {/* 关键位 + 估值 + 相对强弱 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        <div className="bg-gray-800/50 rounded-lg p-2.5">
          <p className="text-[10px] text-gray-500 mb-0.5">支撑 / 压力</p>
          <p className="text-sm font-mono">
            <span className="text-emerald-400">{verdict.support ?? '--'}</span>
            <span className="text-gray-600"> / </span>
            <span className="text-red-400">{verdict.resistance ?? '--'}</span>
          </p>
        </div>
        <div className="bg-gray-800/50 rounded-lg p-2.5">
          <p className="text-[10px] text-gray-500 mb-0.5">当前位置</p>
          <p className="text-xs text-gray-300">{pos.vs_ma ?? '--'}</p>
          <p className="text-[10px] text-gray-500">RSI {pos.rsi ?? '--'}（{pos.rsi_zone ?? '--'}）</p>
        </div>
        <div className="bg-gray-800/50 rounded-lg p-2.5">
          <p className="text-[10px] text-gray-500 mb-0.5">估值分位</p>
          {val && val.pe != null ? (
            <>
              <p className="text-xs text-gray-300">PE {val.pe}{val.pe_pct != null && <span className="text-gray-500"> · {val.pe_pct}%位</span>}</p>
              {val.pb != null && <p className="text-[10px] text-gray-500">PB {val.pb}{val.pb_pct != null && ` · ${val.pb_pct}%位`}</p>}
            </>
          ) : <p className="text-xs text-gray-600">数据源暂不可用</p>}
        </div>
        <div className="bg-gray-800/50 rounded-lg p-2.5">
          <p className="text-[10px] text-gray-500 mb-0.5">距高/低点</p>
          <p className="text-xs">
            <span className={pctColor(pos.from_high_pct)}>{pos.from_high_pct ?? '--'}%</span>
            <span className="text-gray-600"> / </span>
            <span className={pctColor(pos.from_low_pct)}>+{pos.from_low_pct ?? '--'}%</span>
          </p>
        </div>
      </div>

      {/* 相对大盘强弱迷你图 */}
      {rel && (rel.series?.length ?? 0) >= 2 && (
        <div className="bg-gray-800/30 rounded-lg p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] text-gray-400">相对 {rel.index_name ?? '大盘'} 强弱</span>
            <span className="text-[11px]">
              个股 <b className={pctColor(rel.stock_ret)}>{(rel.stock_ret ?? 0) > 0 ? '+' : ''}{rel.stock_ret}%</b>
              <span className="text-gray-600"> vs </span>
              大盘 <b className={pctColor(rel.index_ret)}>{(rel.index_ret ?? 0) > 0 ? '+' : ''}{rel.index_ret}%</b>
              <span className={`ml-2 px-1.5 py-0.5 rounded ${rel.outperform ? 'bg-red-900/40 text-red-300' : 'bg-emerald-900/40 text-emerald-300'}`}>
                {rel.outperform ? '跑赢' : '跑输'} {Math.abs(rel.excess ?? 0)}%
              </span>
            </span>
          </div>
          <RelativeChart rel={rel} />
          <p className="text-[10px] text-gray-600 mt-1">红=个股 / 灰=大盘，均归一化到 100；线在上方=区间内更强</p>
        </div>
      )}
    </div>
  )
}
