import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
  name?: string   // 用于标识是哪个组件崩溃
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error(`[ErrorBoundary:${this.props.name ?? 'unknown'}]`, error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div className="rounded-xl border border-red-800 bg-red-950/40 p-5 text-sm text-red-300 space-y-2">
          <div className="font-semibold flex items-center gap-2">
            <span>⚠️</span>
            <span>渲染出错{this.props.name ? `（${this.props.name}）` : ''}</span>
          </div>
          <div className="text-xs text-red-400/80 font-mono break-all">
            {this.state.error?.message}
          </div>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="text-xs text-red-400 hover:text-red-200 underline"
          >
            重试
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
