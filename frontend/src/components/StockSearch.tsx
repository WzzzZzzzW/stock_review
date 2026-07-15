import { useState, useRef, useEffect, useCallback } from 'react'
import { useStockList, type StockItem } from '../hooks/useStockList'
import { useSearchHistory } from '../hooks/useSearchHistory'

// ── 板块样式 ──────────────────────────────────────────────────────────
const MARKET_STYLE: Record<string, string> = {
  '沪市主板': 'text-red-400   bg-red-900/30',
  '深市主板': 'text-blue-400  bg-blue-900/30',
  '创业板':   'text-green-400 bg-green-900/30',
  '科创板':   'text-yellow-400 bg-yellow-900/30',
  '北交所':   'text-purple-400 bg-purple-900/30',
}

// 热门股票（未搜索时展示）
const HOT_SYMBOLS = [
  '600519','300750','000858','601318','002594',
  '600036','000001','601166','002415','688041',
]

function highlight(text: string, query: string): React.ReactNode {
  if (!query) return text
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return text
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-blue-600/40 text-white rounded-sm">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </>
  )
}

/** 判断查询串是否为纯拼音（只含字母，无数字） */
function isPinyinQuery(q: string): boolean {
  return /^[a-z]+$/.test(q)
}

function searchStocks(stocks: StockItem[], q: string): StockItem[] {
  if (!q.trim()) return []
  const lq = q.trim().toLowerCase()

  const exactCode:    StockItem[] = []
  const prefixCode:   StockItem[] = []
  const pinyinExact:  StockItem[] = []
  const pinyinPrefix: StockItem[] = []
  const nameContain:  StockItem[] = []

  const checkPinyin = isPinyinQuery(lq)

  for (const s of stocks) {
    if (s.symbol === lq)                    { exactCode.push(s);    continue }
    if (s.symbol.startsWith(lq))           { prefixCode.push(s);   continue }
    if (s.name.toLowerCase().includes(lq)) { nameContain.push(s);  continue }
    if (checkPinyin) {
      const py = s.pinyin ?? ''
      if (py === lq)                       { pinyinExact.push(s);  continue }
      if (py.startsWith(lq))              { pinyinPrefix.push(s);  continue }
    }
  }
  return [...exactCode, ...prefixCode, ...pinyinExact, ...pinyinPrefix, ...nameContain].slice(0, 14)
}

/** 搜索项是否通过拼音命中（用于展示拼音标记） */
function matchedByPinyin(s: StockItem, q: string): boolean {
  if (!isPinyinQuery(q)) return false
  const lq = q.toLowerCase()
  const py = s.pinyin ?? ''
  return (py === lq || py.startsWith(lq)) &&
    !s.symbol.startsWith(lq) &&
    !s.name.toLowerCase().includes(lq)
}

interface Props {
  value: string
  onChange: (symbol: string, name: string) => void
  placeholder?: string
  defaultName?: string  // 从外部（如行情页）传入的名称，避免等待股票列表加载
}

export default function StockSearch({ value, onChange, placeholder, defaultName = '' }: Props) {
  const { data: stocks = [], isLoading } = useStockList()
  const { history, addToHistory, removeFromHistory, clearHistory } = useSearchHistory()
  const [query, setQuery]       = useState(value)
  const [open, setOpen]         = useState(false)
  const [cursor, setCursor]     = useState(-1)
  const inputRef  = useRef<HTMLInputElement>(null)
  const listRef   = useRef<HTMLUListElement>(null)
  const wrapRef   = useRef<HTMLDivElement>(null)

  // 选中的股票信息（用于回显名字）
  const [selectedName, setSelectedName] = useState(defaultName)

  // 外部 value 变化时同步（如行情页点击跳转）
  useEffect(() => {
    setQuery(value)
    if (defaultName) setSelectedName(defaultName)
  }, [value, defaultName])

  // 初始化：如果 value 是代码但没有名字，从列表中查找
  useEffect(() => {
    if (value && stocks.length && !selectedName) {
      const found = stocks.find(s => s.symbol === value)
      if (found) setSelectedName(found.name)
    }
  }, [value, stocks, selectedName])

  // 点击组件外关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const results = searchStocks(stocks, query)

  // 热门股（未输入时展示）
  const hotList: StockItem[] = !query.trim()
    ? HOT_SYMBOLS.map(sym => stocks.find(s => s.symbol === sym)).filter(Boolean) as StockItem[]
    : []

  const displayList = query.trim() ? results : hotList

  const select = useCallback((stock: StockItem) => {
    setQuery(stock.symbol)
    setSelectedName(stock.name)
    onChange(stock.symbol, stock.name)
    addToHistory(stock.symbol, stock.name)
    setOpen(false)
    setCursor(-1)
  }, [onChange, addToHistory])

  // 从历史记录中选择
  const selectFromHistory = useCallback((symbol: string, name: string) => {
    setQuery(symbol)
    setSelectedName(name)
    onChange(symbol, name)
    addToHistory(symbol, name)
    setOpen(false)
    setCursor(-1)
  }, [onChange, addToHistory])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open) { if (e.key === 'ArrowDown') setOpen(true); return }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor(c => Math.min(c + 1, displayList.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor(c => Math.max(c - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (cursor >= 0 && displayList[cursor]) select(displayList[cursor])
      else if (displayList[0]) select(displayList[0])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  // 滚动高亮项到可视区
  useEffect(() => {
    if (cursor >= 0 && listRef.current) {
      const item = listRef.current.children[cursor] as HTMLElement
      item?.scrollIntoView({ block: 'nearest' })
    }
  }, [cursor])

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setQuery(val)
    setSelectedName('')
    onChange(val, '')
    setOpen(true)
    setCursor(-1)
  }

  const handleFocus = () => {
    setOpen(true)
    setCursor(-1)
  }

  return (
    <div ref={wrapRef} className="relative">
      {/* 输入框 */}
      <div className={`flex items-center gap-2 bg-gray-800 border rounded-lg px-3 py-2.5 transition-colors ${
        open ? 'border-blue-500' : 'border-gray-700 hover:border-gray-600'
      }`}>
        {/* 搜索图标 */}
        <svg className="w-4 h-4 text-gray-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>

        <div className="flex-1 min-w-0">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={handleInput}
            onFocus={handleFocus}
            onKeyDown={handleKeyDown}
            placeholder={placeholder ?? '搜索股票名称或代码…'}
            autoComplete="off"
            spellCheck={false}
            className="w-full bg-transparent text-white placeholder-gray-500 text-sm outline-none"
          />
          {/* 已选择时显示股票名 */}
          {selectedName && (
            <div className="text-xs text-gray-500 mt-0.5 leading-none">{selectedName}</div>
          )}
        </div>

        {/* 加载指示 & 清空 */}
        {isLoading && (
          <span className="text-xs text-gray-600 animate-pulse shrink-0">加载中…</span>
        )}
        {query && !isLoading && (
          <button onClick={() => { setQuery(''); setSelectedName(''); onChange('', ''); inputRef.current?.focus() }}
            className="text-gray-600 hover:text-gray-400 shrink-0 transition-colors">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        )}
      </div>

      {/* 下拉列表 */}
      {open && (displayList.length > 0 || (!query.trim() && history.length > 0)) && (
        <div className="absolute z-50 w-full mt-1 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl overflow-hidden">

          {/* 历史搜索（仅在未输入时展示） */}
          {!query.trim() && history.length > 0 && (
            <div>
              <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
                <span className="text-xs text-gray-500">最近搜索</span>
                <button
                  onMouseDown={e => { e.preventDefault(); clearHistory() }}
                  className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
                >
                  清除
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5 px-3 py-2.5 border-b border-gray-800">
                {history.slice(0, 10).map(h => (
                  <div key={h.symbol} className="flex items-center gap-1">
                    <button
                      onMouseDown={e => { e.preventDefault(); selectFromHistory(h.symbol, h.name) }}
                      className="flex items-center gap-1 px-2 py-1 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <span className="text-xs font-mono text-gray-300">{h.symbol}</span>
                      <span className="text-xs text-gray-500">{h.name}</span>
                    </button>
                    <button
                      onMouseDown={e => { e.preventDefault(); removeFromHistory(h.symbol) }}
                      className="text-gray-700 hover:text-gray-500 transition-colors"
                    >
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 搜索结果 / 热门 */}
          {displayList.length > 0 && (
            <>
              {!query.trim() && (
                <div className="px-3 py-2 text-xs text-gray-600 border-b border-gray-800">
                  热门股票
                </div>
              )}
              <ul
                ref={listRef}
                className="max-h-64 overflow-y-auto py-1"
              >
                {displayList.map((stock, i) => (
                  <li
                    key={stock.symbol}
                    onMouseDown={e => { e.preventDefault(); select(stock) }}
                    onMouseEnter={() => setCursor(i)}
                    className={`flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-colors ${
                      i === cursor ? 'bg-blue-600/20' : 'hover:bg-gray-800/60'
                    }`}
                  >
                    {/* 代码 */}
                    <span className="font-mono font-bold text-sm text-white w-14 shrink-0">
                      {highlight(stock.symbol, query)}
                    </span>

                    {/* 名称 */}
                    <span className="flex-1 text-sm text-gray-200 truncate">
                      {highlight(stock.name, query)}
                    </span>

                    {/* 拼音命中提示 */}
                    {matchedByPinyin(stock, query) && (
                      <span className="text-xs text-blue-400/70 font-mono shrink-0">
                        {stock.pinyin}
                      </span>
                    )}

                    {/* 板块标签 */}
                    <span className={`text-xs px-1.5 py-0.5 rounded shrink-0 font-medium ${
                      MARKET_STYLE[stock.market] ?? 'text-gray-500 bg-gray-800'
                    }`}>
                      {stock.market}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {query.trim() && results.length === 0 && (
            <div className="px-4 py-5 text-center text-gray-600 text-sm">
              未找到匹配股票
            </div>
          )}
        </div>
      )}
    </div>
  )
}
