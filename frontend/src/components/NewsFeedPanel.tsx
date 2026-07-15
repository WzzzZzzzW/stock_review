import { useState } from 'react'
import { useNewsFeed } from '../hooks/useNewsFeed'
import { useNewsFeedCn } from '../hooks/useNewsFeedCn'
import type { FeedItem } from '../types'

// ── 来源样式配置 ──────────────────────────────────────────────────────
const SOURCE_BADGE: Record<string, string> = {
  '财联社':          'bg-red-900/50 text-red-300 border-red-800/50',
  '东方财富':        'bg-amber-900/50 text-amber-300 border-amber-800/50',
  '同花顺':          'bg-orange-900/50 text-orange-300 border-orange-800/50',
  '富途':            'bg-cyan-900/50 text-cyan-300 border-cyan-800/50',
  '新浪财经':        'bg-rose-900/50 text-rose-300 border-rose-800/50',
  '央视新闻':        'bg-red-950/60 text-red-200 border-red-800/60',
  '财新':            'bg-red-900/40 text-red-300 border-red-800/40',
  'SHMET快讯':       'bg-orange-900/40 text-orange-300 border-orange-800/40',
  'Reuters商业':     'bg-blue-900/40 text-blue-300 border-blue-800/40',
  'Reuters':         'bg-blue-900/40 text-blue-300 border-blue-800/40',
  'BBC商业':         'bg-sky-900/40 text-sky-300 border-sky-800/40',
  'Google财经':      'bg-indigo-900/40 text-indigo-300 border-indigo-800/40',
  '关税贸易':        'bg-purple-900/40 text-purple-300 border-purple-800/40',
  '美联储利率':      'bg-violet-900/40 text-violet-300 border-violet-800/40',
  '大宗商品':        'bg-yellow-900/40 text-yellow-300 border-yellow-800/40',
  '芯片科技':        'bg-cyan-900/40 text-cyan-300 border-cyan-800/40',
}
const DEFAULT_BADGE = 'bg-gray-800 text-gray-400 border-gray-700'

const DIR_ICON   = { positive: '↑', negative: '↓', neutral: '→' }
const DIR_COLOR  = { positive: 'text-green-400', negative: 'text-red-400', neutral: 'text-gray-500' }
const DIR_BG     = { positive: 'bg-green-950/40 border-green-800/40', negative: 'bg-red-950/40 border-red-800/40', neutral: 'bg-gray-900/40 border-gray-800/40' }
const STOCK_COLOR = { positive: 'bg-green-900/50 text-green-300 border-green-800/50', negative: 'bg-red-900/50 text-red-300 border-red-800/50', neutral: 'bg-gray-800/60 text-gray-400 border-gray-700/50' }

function timeAgo(s: string): string {
  if (!s) return ''
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s.slice(0, 16)
    const diffMs = Date.now() - d.getTime()
    if (diffMs < 0) return '刚刚'
    const min = Math.floor(diffMs / 60_000)
    if (min < 1) return '刚刚'
    if (min < 60) return `${min}分钟前`
    const h = Math.floor(min / 60)
    if (h < 24) return `${h}小时前`
    const days = Math.floor(h / 24)
    if (days < 30) return `${days}天前`
    return s.slice(0, 16)
  } catch { return s.slice(0, 16) }
}

function exactTime(s: string): string {
  if (!s) return ''
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return ''
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}

function sourceBadge(src: string) {
  const base = Object.keys(SOURCE_BADGE).find(k => src.startsWith(k))
  return SOURCE_BADGE[base ?? ''] ?? DEFAULT_BADGE
}

// ── 单条新闻卡片 ──────────────────────────────────────────────────────
function NewsCard({ item, onAnalyze }: {
  item: FeedItem
  onAnalyze: (item: FeedItem) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const hasFullContent = item.content && item.content.length > (item.summary?.length ?? 0)
  const displayContent = expanded ? (item.content || item.summary || '') : (item.summary || item.content || '')

  // 是否是"快讯"类型（财联社等无标题/标题就是内容前60字的）
  const isFlash = item.source_type === 'flash'
  const displayTitle = item.title_cn || item.title

  return (
    <article className={`border rounded-xl p-4 transition-all hover:border-gray-700 ${
      item.relevant && item.direction !== 'neutral' ? DIR_BG[item.direction] : 'bg-gray-900/60 border-gray-800'
    }`}>
      {/* 顶部：来源 + 时间 + 方向标 */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className={`text-[11px] font-bold px-2 py-0.5 rounded border ${sourceBadge(item.source)}`}>
          {item.source}
        </span>
        {isFlash && (
          <span className="text-[10px] text-yellow-500 bg-yellow-950/40 border border-yellow-800/40 px-1.5 py-0.5 rounded">
            ⚡快讯
          </span>
        )}
        {item.published && (
          <span className="text-[11px] text-gray-500" title={exactTime(item.published)}>
            {timeAgo(item.published)}
          </span>
        )}
        {item.relevant && item.direction !== 'neutral' && (
          <span className={`text-xs font-bold ${DIR_COLOR[item.direction]}`} title="AI判断对A股影响方向">
            {DIR_ICON[item.direction]} {item.direction === 'positive' ? '利好' : '利空'}
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={() => onAnalyze(item)}
          className="text-[11px] px-2 py-0.5 rounded bg-gray-800 hover:bg-blue-700 text-gray-400 hover:text-white transition-colors"
        >
          🔍 AI深度分析
        </button>
      </div>

      {/* 标题 */}
      <h3 className="text-[15px] font-semibold text-white leading-snug mb-2">
        {displayTitle}
      </h3>
      {item.title_cn && item.title !== item.title_cn && (
        <p className="text-xs text-gray-600 mb-2 leading-relaxed">{item.title}</p>
      )}

      {/* 内容正文 */}
      {displayContent && (
        <div className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
          {expanded ? (
            displayContent
          ) : (
            <span className="line-clamp-3">{displayContent}</span>
          )}
        </div>
      )}

      {/* 展开/收起 + 原文链接 */}
      <div className="flex items-center gap-3 mt-2.5">
        {hasFullContent && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            {expanded ? '收起 ↑' : '展开全文 ↓'}
          </button>
        )}
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            阅读原文 →
          </a>
        )}
      </div>

      {/* AI判断的影响逻辑 */}
      {item.relevant && item.one_line && (
        <div className={`mt-3 px-3 py-2 rounded-lg border text-xs ${DIR_BG[item.direction]}`}>
          <span className="text-gray-500 mr-2">💡 影响逻辑：</span>
          <span className={DIR_COLOR[item.direction]}>{item.one_line}</span>
        </div>
      )}

      {/* 相关个股 */}
      {item.stocks.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <span className="text-[11px] text-gray-600">📌 相关个股：</span>
          {item.stocks.map(s => (
            <span
              key={s}
              className={`text-[11px] px-2 py-0.5 rounded border font-medium ${STOCK_COLOR[item.direction]}`}
            >
              {s}
            </span>
          ))}
        </div>
      )}
    </article>
  )
}

// ── 列表 ──────────────────────────────────────────────────────────────
function FeedList({ items, onAnalyze, isLoading, isError, filter }: {
  items: FeedItem[]
  onAnalyze: (item: FeedItem) => void
  isLoading: boolean
  isError: boolean
  filter: 'all' | 'relevant' | 'flash'
}) {
  if (isLoading) return (
    <div className="px-5 py-12 text-center space-y-3">
      <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
      <p className="text-gray-500 text-sm">正在拉取实时财经快讯并进行 AI 初筛...</p>
      <p className="text-gray-700 text-xs">财联社 · 东方财富 · 同花顺 · 富途 · 新浪 · 央视</p>
    </div>
  )
  if (isError) return (
    <div className="px-5 py-12 text-center text-gray-600 text-sm">
      暂时无法获取新闻源，请稍后刷新
    </div>
  )

  let filtered = items
  if (filter === 'relevant') filtered = items.filter(i => i.relevant)
  else if (filter === 'flash') filtered = items.filter(i => i.source_type === 'flash')

  if (!filtered.length) return (
    <div className="px-5 py-12 text-center text-gray-600 text-sm">
      {filter === 'relevant' ? '当前筛选下暂无相关新闻' : '暂无新闻'}
    </div>
  )

  return (
    <div className="space-y-3 p-4">
      {filtered.map((item, i) => (
        <NewsCard key={`${item.source}-${i}-${item.title.slice(0,20)}`} item={item} onAnalyze={onAnalyze} />
      ))}
    </div>
  )
}

interface Props {
  onAnalyze: (item: FeedItem) => void
}

export default function NewsFeedPanel({ onAnalyze }: Props) {
  const [tab, setTab] = useState<'cn' | 'global'>('cn')
  const [filter, setFilter] = useState<'all' | 'relevant' | 'flash'>('all')

  const cn     = useNewsFeedCn()
  const global = useNewsFeed()

  const active = tab === 'cn' ? cn : global
  const items  = active.data?.items ?? []

  const relevantCount = items.filter(i => i.relevant).length
  const flashCount    = items.filter(i => i.source_type === 'flash').length

  const updatedTime = active.dataUpdatedAt
    ? new Date(active.dataUpdatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : ''

  return (
    <div className="bg-gray-900/40 border border-gray-800 rounded-xl overflow-hidden">
      {/* 头部 */}
      <div className="px-4 py-3 border-b border-gray-800 bg-gray-900/60">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
            <span className="text-sm font-bold text-white">📡 实时财经</span>
            {/* 国内/国际 */}
            <div className="flex gap-1 bg-gray-950/60 rounded-lg p-0.5">
              {([
                { key: 'cn',     label: '🇨🇳 国内' },
                { key: 'global', label: '🌐 国际' },
              ] as const).map(t => (
                <button key={t.key} onClick={() => setTab(t.key)}
                  className={`text-xs px-2.5 py-1 rounded-md transition-colors ${
                    tab === t.key ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-white'
                  }`}>
                  {t.label}
                </button>
              ))}
            </div>
            {updatedTime && (
              <span className="text-[11px] text-gray-600">{updatedTime} 更新</span>
            )}
          </div>
          <button onClick={() => active.refetch()}
            disabled={active.isLoading}
            className="text-xs px-3 py-1 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white transition-colors disabled:opacity-40">
            {active.isLoading ? '获取中...' : '🔄 刷新'}
          </button>
        </div>

        {/* 筛选 */}
        {items.length > 0 && (
          <div className="flex items-center gap-1.5 mt-2 flex-wrap">
            <button
              onClick={() => setFilter('all')}
              className={`text-[11px] px-2.5 py-1 rounded-full transition-colors ${
                filter === 'all' ? 'bg-gray-700 text-white' : 'bg-gray-900/60 text-gray-500 hover:text-gray-300'
              }`}
            >
              全部 ({items.length})
            </button>
            {flashCount > 0 && (
              <button
                onClick={() => setFilter('flash')}
                className={`text-[11px] px-2.5 py-1 rounded-full transition-colors ${
                  filter === 'flash' ? 'bg-yellow-700/60 text-yellow-200' : 'bg-gray-900/60 text-gray-500 hover:text-yellow-300'
                }`}
              >
                ⚡ 快讯 ({flashCount})
              </button>
            )}
            {relevantCount > 0 && (
              <button
                onClick={() => setFilter('relevant')}
                className={`text-[11px] px-2.5 py-1 rounded-full transition-colors ${
                  filter === 'relevant' ? 'bg-blue-700/60 text-blue-200' : 'bg-gray-900/60 text-gray-500 hover:text-blue-300'
                }`}
              >
                🎯 A股相关 ({relevantCount})
              </button>
            )}
          </div>
        )}
      </div>

      {/* 列表 */}
      <FeedList
        items={items}
        onAnalyze={onAnalyze}
        isLoading={active.isLoading}
        isError={active.isError}
        filter={filter}
      />
    </div>
  )
}
