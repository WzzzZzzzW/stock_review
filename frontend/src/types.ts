// ── 功能一：股票复盘 ────────────────────────────────────────────────

export interface OhlcvBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  pct_change: number
  ma5: number
  ma20: number
  ma60: number
}

export interface PriceSummary {
  start_price: number
  end_price: number
  total_return: number
  max_price: number
  min_price: number
  avg_volume: number
  max_volume?: number
  max_vol_date?: string
  gain_days?: number
  loss_days?: number
  price_vs_ma?: string
  latest_rsi: number | null
  latest_macd: number | null
  latest_macd_s?: number | null
  ma5_last?: number | null
  ma20_last?: number | null
  ma60_last?: number | null
}

export interface FinancialScore {
  score: number
  grade: 'A' | 'B' | 'C' | 'D' | 'F'
  flags: string[]
  positives: string[]
}

export interface LhbRecord {
  date: string
  reason: string
  close: number
  pct_chg: number
  net_buy: number
  after_1d: number | string
  after_5d: number | string
}

export interface ReviewValuation {
  pe?: number | null
  pb?: number | null
  pe_pct?: number | null
  pb_pct?: number | null
  mv_yi?: number | null
  as_of?: string
}

export interface ReviewRelative {
  index_name?: string
  stock_ret?: number
  index_ret?: number
  excess?: number
  outperform?: boolean
  series?: { date: string; stock: number; index: number }[]
}

export interface ReviewVerdict {
  stance?: string
  grade?: string
  score?: number
  trend?: string
  tags?: string[]
  bull_ratio?: number
  position?: {
    close?: number
    vs_ma?: string
    rsi?: number | null
    rsi_zone?: string
    from_high_pct?: number | null
    from_low_pct?: number | null
  }
  support?: number
  resistance?: number
  bull_points?: string[]
  bear_points?: string[]
  relative?: ReviewRelative
  valuation?: ReviewValuation
}

export interface ReviewResponse {
  symbol: string
  name: string
  industry?: { name: string; classification: string }
  period: { start: string; end: string }
  report: string
  price_summary: PriceSummary
  ohlcv: OhlcvBar[]
  key_events?: any[]
  indicators: Record<string, number | null>[]
  financial_score?: FinancialScore
  verdict?: ReviewVerdict
  valuation?: ReviewValuation
  relative?: ReviewRelative
  lhb?: LhbRecord[]
  ths_hot?: Record<string, string[]>
  industry_rank?: Record<string, any>
  fund_flow?: Record<string, any>
}

// ── 功能二：新闻 → A股影响分析 ─────────────────────────────────────

export interface AffectedStock {
  symbol: string
  name: string
  sector: string
  direction: 'positive' | 'negative' | 'neutral'
  confidence: number
  reasoning: string
  impact_type: 'direct' | 'indirect'
}

export interface NewsImpactRequest {
  news_text?: string
  url?: string
  news_source?: string
  news_date?: string
}

export interface NewsImpactResponse {
  summary: string
  affected_stocks: AffectedStock[]
  macro_themes: string[]
  risk_warning: string
}

// ── 功能二：新闻推送 ────────────────────────────────────────────────

export interface FeedItem {
  title: string
  url: string
  summary: string
  content?: string        // 全文（财联社/同花顺/富途等）
  published: string
  source: string
  source_type?: string    // flash(快讯) / news / policy
  // AI 初筛字段
  title_cn?: string       // 中文标题翻译（国际新闻）
  relevant: boolean
  direction: 'positive' | 'negative' | 'neutral'
  stocks: string[]        // "公司名(代码)" 格式
  one_line: string
}

export interface NewsFeedResponse {
  items: FeedItem[]
  cached: boolean
  updated_at: number
  error?: string
}
