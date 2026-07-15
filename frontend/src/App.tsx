import { useEffect, useRef, useState } from 'react'
import {
  Archive,
  Bot,
  BrainCircuit,
  BriefcaseBusiness,
  ChartNoAxesCombined,
  Microscope,
  MoonStar,
  Sunrise,
} from 'lucide-react'
import BackgroundTasks from './components/BackgroundTasks'
import ErrorBoundary from './components/ErrorBoundary'
import OfficePage from './pages/OfficePage'
import ResearchToolsPage, { type ResearchSection } from './pages/ResearchToolsPage'
import StrategyCenterPage from './pages/StrategyCenterPage'
import TodayReviewPage from './pages/TodayReviewPage'
import TradingArchivePage from './pages/TradingArchivePage'
import TradingWorkspacePage from './pages/TradingWorkspacePage'
import ZhengxiPage from './pages/ZhengxiPage'

type PhaseTab = 'premarket' | 'intraday' | 'postmarket'
type MainTab = PhaseTab | 'office' | 'zhengxi' | 'research' | 'strategy' | 'archive'

interface MarketStatus {
  phase: PhaseTab
  label: string
  server_time: string
}

function localPhase(): PhaseTab {
  const now = new Date()
  const minutes = now.getHours() * 60 + now.getMinutes()
  if (minutes < 570) return 'premarket'
  if (minutes < 900) return 'intraday'
  return 'postmarket'
}

const primaryTabs = [
  { key: 'premarket' as const, label: '盘前', icon: Sunrise },
  { key: 'intraday' as const, label: '盘中', icon: ChartNoAxesCombined },
  { key: 'postmarket' as const, label: '盘后', icon: MoonStar },
  { key: 'office' as const, label: 'AI办公室', icon: Bot },
  { key: 'zhengxi' as const, label: '郑希投研', icon: BriefcaseBusiness },
]

const utilityTabs = [
  { key: 'research' as const, label: '研究工具', icon: Microscope },
  { key: 'strategy' as const, label: '策略中心', icon: BrainCircuit },
  { key: 'archive' as const, label: '日历档案', icon: Archive },
]

export default function App() {
  const [mainTab, setMainTab] = useState<MainTab>(() => localPhase())
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null)
  const [researchSection, setResearchSection] = useState<ResearchSection>('market')
  const [reviewSymbol, setReviewSymbol] = useState('')
  const [reviewName, setReviewName] = useState('')
  const userSelected = useRef(false)

  useEffect(() => {
    fetch('/api/trading-day/status')
      .then(async response => response.ok ? response.json() : null)
      .then((status: MarketStatus | null) => {
        if (!status) return
        setMarketStatus(status)
        if (!userSelected.current) setMainTab(status.phase)
      })
      .catch(() => {})
  }, [])

  const selectTab = (tab: MainTab) => {
    userSelected.current = true
    setMainTab(tab)
  }

  const handleSelectStock = (symbol: string, name: string) => {
    setReviewSymbol(symbol)
    setReviewName(name)
    setResearchSection('review')
    selectTab('research')
  }

  const openResearch = (section: Exclude<ResearchSection, 'review' | 'screener'>) => {
    setResearchSection(section)
    selectTab('research')
  }

  return (
    <div className="min-h-screen bg-gray-950">
      <nav className="sticky top-0 z-50 border-b border-gray-800 bg-gray-950/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1500px] items-center gap-2 px-3 sm:px-4">
          <div className="mr-1 hidden shrink-0 items-center gap-3 lg:flex">
            <span className="text-sm font-bold text-white">股票分析</span>
            <span className="h-5 w-px bg-gray-800" />
          </div>

          <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {primaryTabs.map(tab => {
              const Icon = tab.icon
              const active = mainTab === tab.key
              const isCurrentPhase = marketStatus?.phase === tab.key
              return (
                <button
                  key={tab.key}
                  onClick={() => selectTab(tab.key)}
                  className={`relative inline-flex h-9 shrink-0 items-center gap-2 rounded px-3 text-sm font-medium transition-colors ${active ? 'bg-blue-600 text-white' : 'text-gray-400 hover:bg-gray-900 hover:text-gray-200'}`}
                >
                  <Icon className="h-4 w-4" />
                  <span>{tab.label}</span>
                  {isCurrentPhase && <span className={`h-1.5 w-1.5 rounded-full ${active ? 'bg-white' : 'bg-emerald-400'}`} title="当前交易阶段" />}
                </button>
              )
            })}
            <div className="mx-1 h-5 w-px shrink-0 bg-gray-800" />
            {utilityTabs.map(tab => {
              const Icon = tab.icon
              const active = mainTab === tab.key
              return (
                <button
                  key={tab.key}
                  onClick={() => selectTab(tab.key)}
                  className={`inline-flex h-9 items-center gap-2 rounded px-2.5 text-xs font-medium transition-colors ${active ? 'bg-gray-700 text-white' : 'text-gray-500 hover:bg-gray-900 hover:text-gray-300'}`}
                  title={tab.label}
                >
                  <Icon className="h-4 w-4" />
                  <span className="hidden xl:inline">{tab.label}</span>
                </button>
              )
            })}
          </div>
          <BackgroundTasks onOpenReview={handleSelectStock} />
        </div>
      </nav>

      {mainTab === 'premarket' && (
        <ErrorBoundary name="premarket">
          <TradingWorkspacePage phase="premarket" onSelectStock={handleSelectStock} onOpenResearch={openResearch} />
        </ErrorBoundary>
      )}
      {mainTab === 'intraday' && (
        <ErrorBoundary name="intraday">
          <TradingWorkspacePage phase="intraday" onSelectStock={handleSelectStock} onOpenResearch={openResearch} />
        </ErrorBoundary>
      )}
      {mainTab === 'postmarket' && <ErrorBoundary name="postmarket"><TodayReviewPage /></ErrorBoundary>}
      {mainTab === 'office' && <ErrorBoundary name="office"><OfficePage /></ErrorBoundary>}
      {mainTab === 'zhengxi' && <ErrorBoundary name="zhengxi"><ZhengxiPage /></ErrorBoundary>}
      {mainTab === 'research' && (
        <ErrorBoundary name="research-tools">
          <ResearchToolsPage
            section={researchSection}
            onSectionChange={setResearchSection}
            reviewSymbol={reviewSymbol}
            reviewName={reviewName}
            onSelectStock={handleSelectStock}
          />
        </ErrorBoundary>
      )}
      {mainTab === 'strategy' && <ErrorBoundary name="strategy-center"><StrategyCenterPage onSelectStock={handleSelectStock} /></ErrorBoundary>}
      {mainTab === 'archive' && <ErrorBoundary name="trading-archive"><TradingArchivePage onSelectStock={handleSelectStock} /></ErrorBoundary>}
    </div>
  )
}
