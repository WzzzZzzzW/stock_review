import { useState } from 'react'
import ErrorBoundary      from './components/ErrorBoundary'
import BackgroundTasks    from './components/BackgroundTasks'
import MarketPage         from './pages/MarketPage'
import ReviewPage         from './pages/ReviewPage'
import NewsImpactPage     from './pages/NewsImpactPage'
import LhbPage            from './pages/LhbPage'
import WatchlistPage      from './pages/WatchlistPage'
import PortfolioPage      from './pages/PortfolioPage'
import TodayReviewPage    from './pages/TodayReviewPage'
import ScreenerPage       from './pages/ScreenerPage'
import LimitUpReviewPage  from './pages/LimitUpReviewPage'
import RuleLibraryPage    from './pages/RuleLibraryPage'
import OfficePage         from './pages/OfficePage'
import BrainPage          from './pages/BrainPage'
import ZhengxiPage        from './pages/ZhengxiPage'
import DraggableNav       from './components/DraggableNav'

// ── 两级导航结构 ─────────────────────────────────────────────────────────────
type MainTab = 'today_review' | 'naoku' | 'brain' | 'office' | 'today' | 'market' | 'research' | 'zhengxi'
type SubTab =
  | 'portfolio' | 'watchlist' | 'rec_today' | 'rec_tomorrow' | 'rec_history'
  | 'quotes' | 'limitup' | 'lhb'
  | 'review' | 'news' | 'screener'

// 自选页内部视图 ←→ App 子tab 的映射（把原来页内的 4 个 tab 提到顶层并列）
type WlView = 'watchlist' | 'today' | 'tomorrow' | 'history'
const WL_VIEW: Partial<Record<SubTab, WlView>> = {
  watchlist:     'watchlist',
  rec_today:     'today',
  rec_tomorrow:  'tomorrow',
  rec_history:   'history',
}

const MAIN_TABS: { key: MainTab; label: string; icon: string; desc: string }[] = [
  { key: 'today_review', label: '今日复盘', icon: '📅', desc: '今天完整复盘' },
  { key: 'naoku',    label: '脑库',     icon: '🧠', desc: '我的交易纪律与买卖心法' },
  { key: 'brain',    label: '规则库',   icon: '🎯', desc: '我的选股规则' },
  { key: 'office',   label: 'AI办公室', icon: '🏢', desc: '8位AI专家随时咨询' },
  { key: 'today',    label: '今日',     icon: '🏠', desc: '今天要做什么' },
  { key: 'market',   label: '市场',     icon: '📊', desc: '市场在发生什么' },
  { key: 'research', label: '研究',     icon: '🔬', desc: '深度分析工具' },
  { key: 'zhengxi',  label: '郑希投研', icon: '🧑‍💼', desc: '景气成长框架 · 观点检索与基金打分' },
]

const SUB_TABS: Record<MainTab, { key: SubTab; label: string }[]> = {
  naoku:  [],
  brain:  [],
  office: [],
  zhengxi: [],
  today_review: [],
  today: [
    { key: 'portfolio',    label: '💼 持仓' },
    { key: 'watchlist',    label: '📌 我的自选' },
    { key: 'rec_today',    label: '🔥 今日推荐' },
    { key: 'rec_tomorrow', label: '🎯 明日预判' },
    { key: 'rec_history',  label: '📜 推荐历史' },
  ],
  market: [
    { key: 'quotes',  label: '📈 大盘行情' },
    { key: 'limitup', label: '🔴 涨停板' },
    { key: 'lhb',     label: '🐉 龙虎榜' },
  ],
  research: [
    { key: 'review',   label: '📊 个股复盘' },
    { key: 'screener', label: '🔍 行业选股' },
    { key: 'news',     label: '🌐 新闻分析' },
  ],
}

const DEFAULT_SUB: Record<MainTab, SubTab | null> = {
  today_review: null,
  naoku:    null,
  brain:    null,
  office:   null,
  zhengxi:  null,
  today:    'portfolio',
  market:   'quotes',
  research: 'review',
}

export default function App() {
  const [mainTab,      setMainTab]      = useState<MainTab>('today')
  const [subTab,       setSubTab]       = useState<SubTab>('portfolio')
  const [reviewSymbol, setReviewSymbol] = useState('')
  const [reviewName,   setReviewName]   = useState('')

  const switchMain = (m: MainTab) => {
    setMainTab(m)
    const def = DEFAULT_SUB[m]
    if (def) setSubTab(def)
  }

  // 跨页面跳转：从其他页面点股票 → 跳到研究·复盘
  const handleSelectStock = (symbol: string, name: string) => {
    setReviewSymbol(symbol)
    setReviewName(name)
    setMainTab('research')
    setSubTab('review')
  }

  const subs = SUB_TABS[mainTab]

  return (
    <div className="min-h-screen bg-gray-950">
      {/* ── 顶级导航 ── */}
      <nav className="sticky top-0 z-50 bg-gray-950/95 backdrop-blur border-b border-gray-800">
        <div className="flex items-center gap-2 h-14 px-4 max-w-7xl mx-auto">
          <span className="text-white font-bold text-sm mr-3 select-none shrink-0">股票分析</span>
          <div className="w-px h-6 bg-gray-700 mr-2 shrink-0" />
          <DraggableNav
            tabs={MAIN_TABS}
            activeKey={mainTab}
            onSelect={k => switchMain(k as MainTab)}
          />
          <div className="flex-1" />
          {/* 后台任务指示器：生成中可放心切走，跑完点一下回到结果 */}
          <BackgroundTasks onOpenReview={handleSelectStock} />
          {/* 当前板块说明 */}
          <span className="text-xs text-gray-600 hidden sm:inline ml-3">
            {MAIN_TABS.find(t => t.key === mainTab)?.desc}
          </span>
        </div>

        {/* ── 二级导航（仅当有子tab时显示） ── */}
        {subs.length > 0 && (
          <div className="border-t border-gray-900 bg-gray-900/40">
            <div className="flex items-center gap-1 px-4 py-2 max-w-7xl mx-auto overflow-x-auto">
              {subs.map(s => (
                <button
                  key={s.key}
                  onClick={() => setSubTab(s.key)}
                  className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors whitespace-nowrap ${
                    subTab === s.key
                      ? 'bg-gray-700 text-white'
                      : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/60'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </nav>

      {/* ── 页面内容（始终挂载以避免重新加载） ── */}
      <div style={{ display: mainTab === 'naoku' ? 'block' : 'none' }}>
        <ErrorBoundary name="naoku"><BrainPage /></ErrorBoundary>
      </div>
      <div style={{ display: mainTab === 'brain' ? 'block' : 'none' }}>
        <ErrorBoundary name="brain"><RuleLibraryPage onSelectStock={handleSelectStock} /></ErrorBoundary>
      </div>
      <div style={{ display: mainTab === 'office' ? 'block' : 'none' }}>
        <ErrorBoundary name="office"><OfficePage /></ErrorBoundary>
      </div>
      <div style={{ display: mainTab === 'zhengxi' ? 'block' : 'none' }}>
        <ErrorBoundary name="zhengxi"><ZhengxiPage /></ErrorBoundary>
      </div>
      <div style={{ display: mainTab === 'today_review' ? 'block' : 'none' }}>
        <ErrorBoundary name="today-review"><TodayReviewPage /></ErrorBoundary>
      </div>

      {/* 今日板块 */}
      <div style={{ display: mainTab === 'today' && subTab === 'portfolio' ? 'block' : 'none' }}>
        <ErrorBoundary name="portfolio"><PortfolioPage /></ErrorBoundary>
      </div>
      <div style={{ display: mainTab === 'today' && subTab in WL_VIEW ? 'block' : 'none' }}>
        <ErrorBoundary name="watchlist">
          <WatchlistPage onSelectStock={handleSelectStock} view={WL_VIEW[subTab] ?? 'watchlist'} />
        </ErrorBoundary>
      </div>

      {/* 市场板块 */}
      <div style={{ display: mainTab === 'market' && subTab === 'quotes' ? 'block' : 'none' }}>
        <ErrorBoundary name="market"><MarketPage onSelectStock={handleSelectStock} /></ErrorBoundary>
      </div>
      <div style={{ display: mainTab === 'market' && subTab === 'limitup' ? 'block' : 'none' }}>
        <ErrorBoundary name="limitup"><LimitUpReviewPage /></ErrorBoundary>
      </div>
      <div style={{ display: mainTab === 'market' && subTab === 'lhb' ? 'block' : 'none' }}>
        <ErrorBoundary name="lhb"><LhbPage onSelectStock={handleSelectStock} /></ErrorBoundary>
      </div>

      {/* 研究板块 */}
      <div style={{ display: mainTab === 'research' && subTab === 'review' ? 'block' : 'none' }}>
        <ErrorBoundary name="review"><ReviewPage defaultSymbol={reviewSymbol} defaultName={reviewName} /></ErrorBoundary>
      </div>
      <div style={{ display: mainTab === 'research' && subTab === 'screener' ? 'block' : 'none' }}>
        <ErrorBoundary name="screener"><ScreenerPage /></ErrorBoundary>
      </div>
      <div style={{ display: mainTab === 'research' && subTab === 'news' ? 'block' : 'none' }}>
        <ErrorBoundary name="news"><NewsImpactPage /></ErrorBoundary>
      </div>
    </div>
  )
}
