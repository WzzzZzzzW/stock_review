import { useState } from 'react'
import { CalendarDays, History } from 'lucide-react'
import ErrorBoundary from '../components/ErrorBoundary'
import TodayReviewPage from './TodayReviewPage'
import WatchlistPage from './WatchlistPage'

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
}

export default function TradingArchivePage({ onSelectStock }: Props) {
  const [section, setSection] = useState<'daily' | 'history'>('daily')
  return (
    <div>
      <div className="border-b border-gray-800 bg-gray-950/95">
        <div className="mx-auto flex max-w-7xl items-center gap-1 px-4 py-2">
          <button
            onClick={() => setSection('daily')}
            className={`inline-flex h-8 items-center gap-2 rounded px-3 text-xs font-medium ${section === 'daily' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:bg-gray-900 hover:text-gray-300'}`}
          >
            <CalendarDays className="h-3.5 w-3.5" />日档案
          </button>
          <button
            onClick={() => setSection('history')}
            className={`inline-flex h-8 items-center gap-2 rounded px-3 text-xs font-medium ${section === 'history' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:bg-gray-900 hover:text-gray-300'}`}
          >
            <History className="h-3.5 w-3.5" />推荐历史
          </button>
        </div>
      </div>
      {section === 'daily' && <ErrorBoundary name="archive-daily"><TodayReviewPage /></ErrorBoundary>}
      {section === 'history' && <ErrorBoundary name="archive-history"><WatchlistPage onSelectStock={onSelectStock} view="history" /></ErrorBoundary>}
    </div>
  )
}
