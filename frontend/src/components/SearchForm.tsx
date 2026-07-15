import { useState, useEffect } from 'react'
import dayjs from 'dayjs'
import StockSearch from './StockSearch'

interface Props {
  onSubmit:       (symbol: string, start: string, end: string) => void
  loading:        boolean
  defaultSymbol?: string
  defaultName?:   string
}

// 快捷时间范围 —— 用「意图」代替「数字」，让选择有意义
const RANGES = [
  { label: '短线情绪', sub: '近1月',  days: 30,  hint: '看近期异动、资金进出和情绪，适合短线手感' },
  { label: '波段趋势', sub: '近3月',  days: 90,  hint: '看一段完整的上涨/下跌波段，最常用的默认视角' },
  { label: '中期趋势', sub: '近6月',  days: 180, hint: '看主升/主跌的中期走势是否还在延续' },
  { label: '大周期·位置', sub: '近1年', days: 365, hint: '看现在处于一年里的高位还是低位，判断估值与安全边际' },
]

export default function SearchForm({ onSubmit, loading, defaultSymbol = '', defaultName = '' }: Props) {
  const [symbol, setSymbol] = useState(defaultSymbol)
  const [name,   setName]   = useState(defaultName)
  const [start,  setStart]  = useState(dayjs().subtract(90, 'day').format('YYYYMMDD'))
  const [end,    setEnd]    = useState(dayjs().format('YYYYMMDD'))
  const [range,  setRange]  = useState(90)

  // 从行情页跳转时预填股票
  useEffect(() => {
    if (defaultSymbol) { setSymbol(defaultSymbol); setName(defaultName) }
  }, [defaultSymbol, defaultName])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!symbol.trim()) return
    onSubmit(symbol.trim(), start, end)
  }

  const applyRange = (days: number) => {
    setRange(days)
    setStart(dayjs().subtract(days, 'day').format('YYYYMMDD'))
    setEnd(dayjs().format('YYYYMMDD'))
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* 选股器 */}
      <div className="space-y-1">
        <label className="text-xs text-gray-400">股票</label>
        <StockSearch
          value={symbol}
          defaultName={defaultName}
          onChange={(sym, nm) => { setSymbol(sym); setName(nm) }}
          placeholder="搜索股票名称或代码，如 茅台 / 600519"
        />
      </div>

      {/* 时间区间 */}
      <div className="flex flex-wrap items-end gap-3">
        {/* 快捷范围按钮 —— 按「分析意图」选择 */}
        <div className="space-y-1">
          <label className="text-xs text-gray-400">看什么周期？</label>
          <div className="flex gap-1.5">
            {RANGES.map(r => (
              <button
                key={r.days}
                type="button"
                title={r.hint}
                onClick={() => applyRange(r.days)}
                className={`flex flex-col items-center leading-tight px-2.5 py-1.5 rounded-lg transition-colors ${
                  range === r.days
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700'
                }`}
              >
                <span className="text-xs font-medium">{r.label}</span>
                <span className={`text-[10px] ${range === r.days ? 'text-blue-200' : 'text-gray-500'}`}>{r.sub}</span>
              </button>
            ))}
          </div>
          {/* 当前选择的意图说明 */}
          {RANGES.find(r => r.days === range) && (
            <p className="text-[11px] text-gray-500 pt-0.5">
              {RANGES.find(r => r.days === range)!.hint}
            </p>
          )}
        </div>

        {/* 开始日期 */}
        <div className="space-y-1">
          <label className="text-xs text-gray-400">开始日期</label>
          <input
            type="date"
            value={dayjs(start, 'YYYYMMDD').format('YYYY-MM-DD')}
            onChange={e => { setStart(e.target.value.replace(/-/g, '')); setRange(0) }}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200
                       focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        {/* 结束日期 */}
        <div className="space-y-1">
          <label className="text-xs text-gray-400">结束日期</label>
          <input
            type="date"
            value={dayjs(end, 'YYYYMMDD').format('YYYY-MM-DD')}
            onChange={e => { setEnd(e.target.value.replace(/-/g, '')); setRange(0) }}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200
                       focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        {/* 提交 */}
        <button
          type="submit"
          disabled={loading || !symbol.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500
                     text-white rounded-lg px-6 py-2.5 text-sm font-medium transition-colors"
        >
          {loading ? '生成中...' : '生成复盘报告'}
        </button>
      </div>

      {/* 已选股票回显 */}
      {symbol && name && (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span className="font-mono text-gray-400">{symbol}</span>
          <span>·</span>
          <span>{name}</span>
        </div>
      )}
    </form>
  )
}
