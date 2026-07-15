import type { AffectedStock } from '../types'

interface Props {
  stock: AffectedStock
}

const DIRECTION_CONFIG = {
  positive: {
    border: 'border-l-green-500',
    bg: 'bg-green-500',
    text: 'text-green-400',
    label: '利好',
    icon: '↑',
    badge: 'bg-green-900/40 text-green-300',
  },
  negative: {
    border: 'border-l-red-500',
    bg: 'bg-red-500',
    text: 'text-red-400',
    label: '利空',
    icon: '↓',
    badge: 'bg-red-900/40 text-red-300',
  },
  neutral: {
    border: 'border-l-gray-500',
    bg: 'bg-gray-500',
    text: 'text-gray-400',
    label: '中性',
    icon: '→',
    badge: 'bg-gray-700/60 text-gray-300',
  },
}

export default function StockImpactCard({ stock }: Props) {
  const cfg = DIRECTION_CONFIG[stock.direction] ?? DIRECTION_CONFIG.neutral
  const pct = Math.round(stock.confidence * 100)

  return (
    <div className={`bg-gray-900 border border-gray-800 border-l-4 ${cfg.border} rounded-xl p-4 flex flex-col gap-3`}>
      {/* 顶部：代码 + 名称 + impact_type 标签 */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="text-white font-bold text-base">{stock.symbol}</span>
          <span className="text-gray-300 ml-2">{stock.name}</span>
          <div className="text-gray-500 text-xs mt-0.5">{stock.sector}</div>
        </div>
        <span
          className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${
            stock.impact_type === 'direct'
              ? 'bg-blue-900/50 text-blue-300'
              : 'bg-gray-700/60 text-gray-400'
          }`}
        >
          {stock.impact_type === 'direct' ? '直接影响' : '间接影响'}
        </span>
      </div>

      {/* 方向 + 置信度进度条 */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-sm">
          <span className={`font-semibold ${cfg.text}`}>
            {cfg.icon} {cfg.label}
          </span>
          <span className="text-gray-400 text-xs">置信度 {pct}%</span>
        </div>
        <div className="h-1.5 w-full bg-gray-800 rounded-full overflow-hidden">
          <div
            className={`h-full ${cfg.bg} rounded-full transition-all duration-500`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* 推理文字 */}
      <p className="text-gray-400 text-sm leading-relaxed">{stock.reasoning}</p>
    </div>
  )
}
