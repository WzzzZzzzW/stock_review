/**
 * A 股影响力热搜榜（国内 + 国际并列）
 * 取代旧的"实时财经"单栏列表：左栏国内、右栏国际，
 * 每条按 A 股影响力热度排序，同事件多源已聚类合并。
 */
import { useNewsTrending, type TrendingItem } from '../hooks/useNewsTrending'
import type { FeedItem } from '../types'

const DIR_ICON  = { positive: '↑', negative: '↓', neutral: '·' } as const
const DIR_COLOR = {
  positive: 'text-red-400',     // A 股惯例：涨/利好红
  negative: 'text-green-400',
  neutral:  'text-gray-500',
} as const
const DIR_LABEL = { positive: '利好', negative: '利空', neutral: '中性' } as const
const RANK_COLOR = (i: number) =>
  i === 1 ? 'bg-red-600 text-white'
  : i === 2 ? 'bg-orange-500 text-white'
  : i === 3 ? 'bg-amber-500 text-white'
  : 'bg-gray-800 text-gray-400'

function timeAgo(s: string): string {
  if (!s) return ''
  try {
    const d = new Date(s); if (isNaN(d.getTime())) return ''
    const min = Math.floor((Date.now() - d.getTime()) / 60_000)
    if (min < 1) return '刚刚'
    if (min < 60) return `${min}分钟前`
    const h = Math.floor(min / 60)
    if (h < 24) return `${h}小时前`
    return `${Math.floor(h / 24)}天前`
  } catch { return '' }
}

function trendingToFeed(it: TrendingItem): FeedItem {
  // 适配旧的 onAnalyze 回调（NewsImpactPage 的「分析影响」表单要 FeedItem 形状）
  return {
    title:     it.title,
    title_cn:  it.title,
    summary:   it.summary || it.one_line,
    content:   it.summary,
    source:    it.sources[0] || '',
    source_type: 'flash',
    url:       it.url,
    published: it.published,
    relevant:  true,
    direction: it.direction,
    stocks:    it.stocks,
    one_line:  it.one_line,
  } as FeedItem
}

function TrendingCard({ item, onAnalyze }: { item: TrendingItem; onAnalyze: (it: TrendingItem) => void }) {
  const more = item.sources.length > 3
  const showSrcs = item.sources.slice(0, 3)
  return (
    <li className="border border-gray-800 rounded-lg p-2.5 bg-gray-900/40 hover:bg-gray-900/70 transition-colors">
      <div className="flex items-start gap-2">
        <span className={`flex-shrink-0 w-6 h-6 rounded text-[11px] font-bold flex items-center justify-center ${RANK_COLOR(item.rank)}`}>
          {item.rank}
        </span>
        <div className="flex-1 min-w-0">
          {/* 标题 */}
          <div className="flex items-start justify-between gap-2">
            <h4 className="text-[13px] font-semibold text-gray-100 leading-snug flex-1">
              {item.title}
            </h4>
            <button onClick={() => onAnalyze(item)}
              title="把这条新闻送进下方的「分析影响」做 AI 深度分析"
              className="flex-shrink-0 text-[10px] text-blue-400 hover:text-blue-300 border border-blue-900/50 rounded px-1.5 py-0.5">
              深度
            </button>
          </div>
          {/* 一句话影响 + 方向 */}
          {(item.one_line || item.direction !== 'neutral') && (
            <div className="mt-1 flex items-center gap-1.5 text-[11px]">
              <span className={`font-bold ${DIR_COLOR[item.direction]}`}>
                {DIR_ICON[item.direction]} {DIR_LABEL[item.direction]}
              </span>
              {item.one_line && (
                <span className="text-gray-400 truncate">{item.one_line}</span>
              )}
            </div>
          )}
          {/* 个股 chips */}
          {item.stocks.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {item.stocks.slice(0, 5).map(s => (
                <span key={s} className={`text-[10px] px-1.5 py-0.5 rounded border ${
                  item.direction === 'positive' ? 'bg-red-950/40 text-red-300 border-red-900/40'
                  : item.direction === 'negative' ? 'bg-green-950/40 text-green-300 border-green-900/40'
                  : 'bg-gray-800/60 text-gray-400 border-gray-700/40'
                }`}>{s}</span>
              ))}
            </div>
          )}
          {/* 来源 + 时间 + 聚类指示 + 热度 */}
          <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-gray-500 flex-wrap">
            {showSrcs.map(s => (
              <span key={s} className="px-1 py-0.5 rounded bg-gray-800/70 text-gray-400">{s}</span>
            ))}
            {more && <span className="text-gray-600">+{item.sources.length - 3}家</span>}
            {item.cluster_size > 1 && (
              <span className="text-amber-500" title="多家媒体报道">📡 {item.cluster_size}条</span>
            )}
            {item.published && <span>· {timeAgo(item.published)}</span>}
            <span className="ml-auto text-gray-600">🔥 {item.hotness.toFixed(0)}</span>
          </div>
        </div>
      </div>
    </li>
  )
}

function TrendingColumn({ market, onAnalyze }: { market: 'cn' | 'intl'; onAnalyze: (it: FeedItem) => void }) {
  const q = useNewsTrending(market)
  const items = q.data?.items ?? []
  const updated = q.data?.updated_at
    ? new Date(q.data.updated_at * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : ''
  const label = market === 'cn' ? '🇨🇳 国内热搜' : '🌐 国际热搜'

  return (
    <section className="bg-gray-900/40 border border-gray-800 rounded-xl overflow-hidden flex flex-col">
      <header className="px-3 py-2 border-b border-gray-800 bg-gray-900/60 flex items-center gap-2">
        <span className="text-sm font-bold text-white">{label}</span>
        {q.data && (
          <span className="text-[10px] text-gray-600">基于 {q.data.raw_count} 条 · 聚类后 {items.length} 条</span>
        )}
        <div className="flex-1" />
        {updated && <span className="text-[10px] text-gray-600">{updated} 更新</span>}
        <button onClick={() => q.refresh()} disabled={q.isFetching}
          className="text-[11px] px-2 py-0.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white disabled:opacity-40">
          {q.isFetching ? '…' : '🔄'}
        </button>
      </header>
      <ol className="flex-1 overflow-y-auto p-2 space-y-2 max-h-[640px]">
        {q.isLoading && (
          <div className="py-10 text-center text-gray-600 text-xs">
            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
            正在抓取 + AI 打分…
          </div>
        )}
        {q.isError && (
          <div className="py-10 text-center text-red-400/80 text-xs">
            拉取失败，<button onClick={() => q.refresh()} className="underline">点此重试</button>
          </div>
        )}
        {!q.isLoading && !q.isError && items.length === 0 && (
          <div className="py-10 text-center text-gray-600 text-xs">暂无热搜数据</div>
        )}
        {items.map(it => (
          <TrendingCard key={`${market}-${it.rank}`} item={it}
            onAnalyze={x => onAnalyze(trendingToFeed(x))} />
        ))}
      </ol>
    </section>
  )
}

export default function NewsTrendingPanel({ onAnalyze }: { onAnalyze: (item: FeedItem) => void }) {
  return (
    <div>
      <div className="mb-2 flex items-end gap-3">
        <h3 className="text-sm font-bold text-white">📡 A 股影响力热搜榜</h3>
        <p className="text-[11px] text-gray-500">
          按"来源权威 × 新鲜度 × 跨源报道数 × 关键词 × A 股影响方向"综合打分；同事件多源已聚类合并
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <TrendingColumn market="cn"   onAnalyze={onAnalyze} />
        <TrendingColumn market="intl" onAnalyze={onAnalyze} />
      </div>
    </div>
  )
}
