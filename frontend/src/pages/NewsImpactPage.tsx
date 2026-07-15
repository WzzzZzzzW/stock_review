import { useState, useRef } from 'react'
import StockImpactCard from '../components/StockImpactCard'
import NewsTrendingPanel from '../components/NewsTrendingPanel'
import { useNewsImpact } from '../hooks/useNewsImpact'
import type { FeedItem } from '../types'

const EXAMPLE_NEWS = [
  {
    label: '美国加征关税',
    text: 'The United States announced sweeping tariffs of 25% on all Chinese manufactured goods, including electronics, machinery, and automotive components. The measures take effect immediately and cover over $300 billion in annual trade. China vows retaliation.',
  },
  {
    label: '油价暴跌',
    text: 'Crude oil prices plummeted more than 8% on Monday after OPEC+ members failed to reach a production cut agreement. Brent crude fell to $62 per barrel, the lowest level in two years, as Saudi Arabia signaled it would increase output to defend market share.',
  },
  {
    label: '美联储暂停加息',
    text: 'The Federal Reserve held interest rates steady for the third consecutive meeting, signaling that the tightening cycle may have peaked. Fed Chair Jerome Powell indicated that rate cuts could begin as early as the second half of 2025 if inflation continues to cool.',
  },
  {
    label: '芯片出口管制',
    text: 'The U.S. Commerce Department expanded its chip export restrictions to include advanced AI accelerators and memory chips destined for China. NVIDIA, AMD, and Intel shares fell sharply on fears of lost revenue, while Chinese chipmakers surged on expectations of domestic substitution demand.',
  },
]

function isUrl(s: string) {
  return /^https?:\/\//i.test(s.trim())
}

export default function NewsImpactPage() {
  const [input, setInput] = useState('')
  const [newsSource, setNewsSource] = useState('')
  const [newsDate, setNewsDate] = useState('')
  const { mutate, data, isPending, error, reset } = useNewsImpact()
  const resultRef = useRef<HTMLDivElement>(null)

  const inputIsUrl = isUrl(input)

  const handleSubmit = () => {
    const val = input.trim()
    if (!val) return
    reset()
    if (inputIsUrl) {
      mutate({ url: val, news_source: newsSource, news_date: newsDate })
    } else {
      mutate({ news_text: val, news_source: newsSource, news_date: newsDate })
    }
    // 分析完成后滚动到结果
    setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 500)
  }

  // 推送面板点击"详细分析"——用完整内容做深度分析
  const handleFeedAnalyze = (item: FeedItem) => {
    reset()
    // 优先用完整内容（财联社/同花顺/富途等都有全文），其次用 summary
    const fullText = [
      item.title_cn || item.title,
      item.content || item.summary,
    ].filter(Boolean).join('\n\n')

    if (fullText && fullText.length > 100) {
      // 内容足够，直接用文本分析（避免抓取链接的不确定性）
      setInput(fullText)
      setNewsSource(item.source)
      mutate({ news_text: fullText, news_source: item.source, news_date: item.published })
    } else if (item.url) {
      // 内容不足，回退到链接抓取
      setInput(item.url)
      setNewsSource(item.source)
      mutate({ url: item.url, news_source: item.source })
    } else {
      const text = [item.title, item.summary].filter(Boolean).join('\n\n')
      setInput(text)
      setNewsSource(item.source)
      mutate({ news_text: text, news_source: item.source })
    }
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const positiveCount = data?.affected_stocks.filter(s => s.direction === 'positive').length ?? 0
  const negativeCount = data?.affected_stocks.filter(s => s.direction === 'negative').length ?? 0

  return (
    <div className="min-h-screen bg-gray-950 px-4 py-8">
      <div className="max-w-5xl mx-auto space-y-6">

        {/* 标题 */}
        <div>
          <h1 className="text-2xl font-bold text-white">国际新闻 → A股影响分析</h1>
          <p className="text-sm text-gray-500 mt-1">粘贴新闻原文或链接，AI 识别相关A股及影响方向</p>
        </div>

        {/* 输入区 */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">

          {/* 快捷示例 */}
          <div className="flex flex-wrap gap-2">
            <span className="text-xs text-gray-500 self-center">快速示例：</span>
            {EXAMPLE_NEWS.map(ex => (
              <button
                key={ex.label}
                onClick={() => setInput(ex.text)}
                className="text-xs px-3 py-1 rounded-full bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
              >
                {ex.label}
              </button>
            ))}
          </div>

          {/* 输入框 */}
          <div className="relative">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
              }}
              placeholder={
                inputIsUrl
                  ? '已识别为链接，点击「分析影响」将自动抓取文章...'
                  : '粘贴新闻原文（中英文均可）或新闻链接 URL...'
              }
              rows={inputIsUrl ? 2 : 7}
              maxLength={5000}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-gray-200 placeholder-gray-600 text-sm resize-none focus:outline-none focus:border-blue-500 transition-all duration-200"
            />
            {/* URL 识别徽标 */}
            {inputIsUrl && (
              <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-blue-900/60 text-blue-300 text-xs px-2.5 py-1 rounded-full">
                <span>🔗</span>
                <span>链接模式</span>
              </div>
            )}
            {!inputIsUrl && (
              <span className="absolute bottom-3 right-3 text-xs text-gray-600">
                {input.length}/5000
              </span>
            )}
          </div>

          {/* 可选字段 + 提交 */}
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-28">
              <label className="block text-xs text-gray-500 mb-1">来源（选填）</label>
              <input
                value={newsSource}
                onChange={e => setNewsSource(e.target.value)}
                placeholder="Reuters / Bloomberg..."
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-300 text-sm placeholder-gray-600 focus:outline-none focus:border-blue-500 transition-colors"
              />
            </div>
            <div className="w-40">
              <label className="block text-xs text-gray-500 mb-1">日期（选填）</label>
              <input
                type="date"
                value={newsDate}
                onChange={e => setNewsDate(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-300 text-sm focus:outline-none focus:border-blue-500 transition-colors"
              />
            </div>
            <div className="flex flex-col gap-1">
              <button
                onClick={handleSubmit}
                disabled={isPending || !input.trim()}
                className="px-6 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {isPending
                  ? inputIsUrl ? '抓取并分析中...' : '分析中...'
                  : inputIsUrl ? '🔗 获取并分析' : '分析影响'}
              </button>
              <span className="text-xs text-gray-700 text-center">⌘ Enter</span>
            </div>
          </div>
        </div>

        {/* 错误 */}
        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-xl p-4 text-red-300 text-sm">
            {error.message}
          </div>
        )}

        {/* 加载中 */}
        {isPending && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
            <div className="text-gray-400 text-sm animate-pulse">
              {inputIsUrl
                ? 'AI 正在抓取文章并分析传导路径，约需 10~20 秒...'
                : 'AI 正在分析新闻传导路径，识别相关A股，约需 5~15 秒...'}
            </div>
          </div>
        )}

        {/* 没识别到个股：多半是把这里当成"问答/选股"用了 —— 给出明确指引 */}
        {data && !isPending && data.affected_stocks.length === 0 && (
          <div ref={resultRef} className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4">
            <div className="flex items-start gap-3">
              <span className="text-2xl">📭</span>
              <div>
                <div className="text-white font-semibold">没有识别到受影响的个股</div>
                {data.summary && (
                  <p className="text-sm text-gray-400 mt-1">{data.summary}</p>
                )}
              </div>
            </div>
            <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-4 text-sm text-gray-300 leading-relaxed space-y-2">
              <p>
                这个页面是<span className="text-blue-300 font-medium">「新闻 → 影响个股」</span>分析器：
                粘贴一段<span className="text-white font-medium">新闻原文或链接</span>，AI 会帮你找出受影响的 A 股。
                <span className="text-gray-400">你不需要自己给股票代码——它会替你找出代码。</span>
              </p>
              <p className="text-gray-400">
                它<span className="text-amber-300">不是问答助手</span>，直接提问（比如"有什么推荐的股票"）不会有结果，
                因为没有新闻可分析。
              </p>
            </div>
            <div className="text-sm text-gray-400">
              <span className="text-gray-500">想找别的功能：</span>
              <span className="inline-block bg-gray-800 text-gray-200 rounded px-2 py-0.5 mx-1">🔍 行业选股</span>挑标的、
              <span className="inline-block bg-gray-800 text-gray-200 rounded px-2 py-0.5 mx-1">📊 个股复盘</span>看单只股票，
              都在顶部导航栏。
            </div>
          </div>
        )}

        {/* 分析结果 */}
        {data && !isPending && data.affected_stocks.length > 0 && (
          <div ref={resultRef} className="space-y-4">
            {/* 事件摘要 + 宏观主题 */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="text-xs text-gray-500 mb-1.5">事件摘要</div>
                  <p className="text-gray-200 text-sm leading-relaxed">{data.summary}</p>
                </div>
                {data.macro_themes.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 max-w-xs">
                    {data.macro_themes.map(theme => (
                      <span key={theme} className="text-xs px-2.5 py-0.5 bg-blue-900/50 text-blue-300 rounded-full">
                        {theme}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex gap-5 mt-4 pt-4 border-t border-gray-800">
                <div className="text-center">
                  <div className="text-xl font-bold text-green-400">{positiveCount}</div>
                  <div className="text-xs text-gray-500 mt-0.5">利好个股</div>
                </div>
                <div className="text-center">
                  <div className="text-xl font-bold text-red-400">{negativeCount}</div>
                  <div className="text-xs text-gray-500 mt-0.5">利空个股</div>
                </div>
                <div className="text-center">
                  <div className="text-xl font-bold text-gray-300">
                    {data.affected_stocks.length - positiveCount - negativeCount}
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">中性个股</div>
                </div>
                <div className="text-center ml-auto">
                  <div className="text-xl font-bold text-white">{data.affected_stocks.length}</div>
                  <div className="text-xs text-gray-500 mt-0.5">共识别</div>
                </div>
              </div>
            </div>

            {/* 股票卡片 */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {data.affected_stocks.map(stock => (
                <StockImpactCard key={stock.symbol} stock={stock} />
              ))}
            </div>

            <p className="text-center text-xs text-gray-600 italic">{data.risk_warning}</p>
          </div>
        )}

        {/* A 股影响力热搜榜（国内 + 国际双栏） */}
        <NewsTrendingPanel onAnalyze={handleFeedAnalyze} />

      </div>
    </div>
  )
}
