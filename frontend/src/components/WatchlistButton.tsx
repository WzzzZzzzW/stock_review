/**
 * 加自选按钮 —— 可丢到任何显示股票的地方（规则库结果、推荐卡、龙虎榜、涨停板…）
 * 点一下加/取消，所有页面通过 watchlistStore 实时同步。
 *
 * 用法：<WatchlistButton code={s.symbol} name={s.name} />
 *   variant="star"（默认）：一颗星图标，适合塞在行/卡片角落
 *   variant="chip"：带文字「+自选 / 已自选」，适合需要明确提示的地方
 */
import { watchlistStore, useInWatchlist } from '../stores/watchlistStore'

interface Props {
  code: string
  name?: string
  variant?: 'star' | 'chip'
  className?: string
}

export default function WatchlistButton({ code, name, variant = 'star', className = '' }: Props) {
  const inList = useInWatchlist(code)

  const onClick = (e: React.MouseEvent) => {
    e.stopPropagation()   // 常嵌在可点击的行/卡片里，别触发外层跳转
    e.preventDefault()
    watchlistStore.toggle(code, name)
  }

  if (variant === 'chip') {
    return (
      <button
        onClick={onClick}
        title={inList ? '已在自选，点击移除' : '加入自选'}
        className={`text-[11px] px-2 py-0.5 rounded border font-medium transition-colors ${
          inList
            ? 'bg-amber-900/40 text-amber-300 border-amber-700/50 hover:bg-amber-900/60'
            : 'bg-gray-800 text-gray-400 border-gray-700 hover:text-amber-300 hover:border-amber-700/50'
        } ${className}`}
      >
        {inList ? '★ 已自选' : '+ 自选'}
      </button>
    )
  }

  // star 图标版
  return (
    <button
      onClick={onClick}
      title={inList ? '已在自选，点击移除' : '加入自选'}
      className={`shrink-0 text-base leading-none transition-colors ${
        inList ? 'text-amber-400 hover:text-amber-300' : 'text-gray-600 hover:text-amber-400'
      } ${className}`}
    >
      {inList ? '★' : '☆'}
    </button>
  )
}
