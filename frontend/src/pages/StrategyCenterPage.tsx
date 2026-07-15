import { useState } from 'react'
import { Brain, FlaskConical, LibraryBig } from 'lucide-react'
import ErrorBoundary from '../components/ErrorBoundary'
import BrainPage from './BrainPage'
import QuantPage from './QuantPage'
import RuleLibraryPage from './RuleLibraryPage'

type StrategySection = 'brain' | 'rules' | 'backtest'

interface Props {
  onSelectStock?: (symbol: string, name: string) => void
}

const tabs = [
  { key: 'brain' as const, label: '脑库', icon: Brain },
  { key: 'rules' as const, label: '规则库', icon: LibraryBig },
  { key: 'backtest' as const, label: '回测', icon: FlaskConical },
]

export default function StrategyCenterPage({ onSelectStock }: Props) {
  const [section, setSection] = useState<StrategySection>('brain')

  return (
    <div>
      <div className="border-b border-gray-800 bg-gray-950/95">
        <div className="mx-auto flex max-w-7xl items-center gap-1 overflow-x-auto px-4 py-2">
          {tabs.map(tab => {
            const Icon = tab.icon
            return (
              <button
                key={tab.key}
                onClick={() => setSection(tab.key)}
                className={`inline-flex h-8 shrink-0 items-center gap-2 rounded px-3 text-xs font-medium transition-colors ${section === tab.key ? 'bg-gray-700 text-white' : 'text-gray-500 hover:bg-gray-900 hover:text-gray-300'}`}
              >
                <Icon className="h-3.5 w-3.5" />{tab.label}
              </button>
            )
          })}
        </div>
      </div>
      {section === 'brain' && <ErrorBoundary name="strategy-brain"><BrainPage /></ErrorBoundary>}
      {section === 'rules' && <ErrorBoundary name="strategy-rules"><RuleLibraryPage onSelectStock={onSelectStock} /></ErrorBoundary>}
      {section === 'backtest' && <ErrorBoundary name="strategy-backtest"><QuantPage onSelectStock={onSelectStock} /></ErrorBoundary>}
    </div>
  )
}
