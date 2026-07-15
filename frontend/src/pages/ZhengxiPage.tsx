/**
 * 郑希投研 —— 独立功能页
 * 三块能力：
 *   1. 请教郑希：对话式投资导师（RAG，回答基于他的真实语料 + 方法论）
 *   2. 投资方法论：method.md / scorecard.md 阅读
 *   3. 基金风格打分：准备证据档案 + AI 按六维 scorecard 打分
 *
 * 红线：原话与语料一致、不臆造数字（缺数据标"需核实"）；研究学习辅助，非投资建议、不荐股。
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type Section = 'chat' | 'method' | 'score'

const SECTIONS: { key: Section; label: string; icon: string; desc: string }[] = [
  { key: 'chat',   label: '请教郑希',   icon: '💬', desc: '像他在旁边一样，对话式教你投资' },
  { key: 'method', label: '投资方法论', icon: '📖', desc: '景气成长框架 + 六维风格评分卡' },
  { key: 'score',  label: '基金风格打分', icon: '🎯', desc: '看某只基金与郑希风格的契合度' },
]

export default function ZhengxiPage() {
  const [section, setSection] = useState<Section>('chat')

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      {/* 页头 */}
      <div className="mb-5">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <span>🧑‍💼 郑希投研</span>
          <span className="text-xs text-gray-500 font-normal">易方达 · 景气成长投资框架</span>
        </h1>
        <p className="text-xs text-gray-500 mt-1">
          基于公开语料（采访 / 季报 / 手记）整理。原话可溯源、不臆造数字；研究学习辅助，<b className="text-gray-400">非投资建议、不荐股</b>。
        </p>
      </div>

      {/* 分段导航 */}
      <div className="flex gap-2 mb-5 flex-wrap">
        {SECTIONS.map(s => (
          <button
            key={s.key}
            onClick={() => setSection(s.key)}
            title={s.desc}
            className={`flex flex-col items-start px-4 py-2.5 rounded-xl border transition-all min-w-[160px] ${
              section === s.key
                ? 'bg-blue-600/20 border-blue-600/60 text-white'
                : 'bg-gray-900 border-gray-800 text-gray-400 hover:border-gray-700 hover:text-gray-200'
            }`}
          >
            <span className="text-sm font-medium flex items-center gap-1.5">{s.icon} {s.label}</span>
            <span className="text-[10px] text-gray-500 mt-0.5">{s.desc}</span>
          </button>
        ))}
      </div>

      {section === 'chat'   && <ChatSection />}
      {section === 'method' && <MethodSection />}
      {section === 'score'  && <ScoreSection />}
    </div>
  )
}

// ── 1. 请教郑希（对话式导师）──────────────────────────────────────────────────

interface LoadedStock { code: string; name: string; price?: number | null; pct?: number | null; roe?: number | null; pe?: number | null }
interface ChatMsg { role: 'user' | 'assistant'; content: string; stocks?: LoadedStock[] }

const STARTERS = [
  '我用基金重仓股选股，但买卖点总把握不好，涨太高不敢买、跌太狠也不敢买，怎么办？',
  '怎么判断一个行业是不是处在高景气阶段？',
  '你为什么偏爱低 ROE 的资产？普通人能学吗？',
  '一只票跌了很多，我怎么判断该抄底还是该躲？',
  '你说的"周期拼接"到底是什么意思？',
]

function ChatSection() {
  const [msgs, setMsgs]       = useState<ChatMsg[]>([])
  const [input, setInput]     = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError]     = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs, streaming])

  const send = useCallback(async (text: string) => {
    const q = text.trim()
    if (!q || streaming) return
    setError(''); setInput('')
    const history = [...msgs, { role: 'user' as const, content: q }]
    setMsgs([...history, { role: 'assistant', content: '' }])
    setStreaming(true)
    try {
      const res = await fetch('/api/zhengxi/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history }),
      })
      if (!res.ok || !res.body) {
        const e = await res.json().catch(() => ({}))
        throw new Error((e as { detail?: string }).detail || '请求失败')
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = '', text2 = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue
          let chunk: unknown
          try { chunk = JSON.parse(raw) } catch { chunk = raw }
          if (chunk === '[DONE]') { setStreaming(false); return }
          // meta 帧：后端识别到的个股已加载数据
          if (chunk && typeof chunk === 'object' && '_stocks' in chunk) {
            const stocks = (chunk as { _stocks: LoadedStock[] })._stocks
            setMsgs(prev => {
              const next = [...prev]
              next[next.length - 1] = { ...next[next.length - 1], stocks }
              return next
            })
            continue
          }
          text2 += typeof chunk === 'string' ? chunk : String(chunk)
          setMsgs(prev => {
            const next = [...prev]
            next[next.length - 1] = { ...next[next.length - 1], role: 'assistant', content: text2 }
            return next
          })
        }
      }
      setStreaming(false)
    } catch (e) {
      setStreaming(false)
      setError(e instanceof Error ? e.message : String(e))
      // 移除占位的空 assistant 气泡
      setMsgs(prev => {
        const next = [...prev]
        if (next.length && next[next.length - 1].role === 'assistant' && !next[next.length - 1].content) next.pop()
        return next
      })
    }
  }, [msgs, streaming])

  const empty = msgs.length === 0

  return (
    <div className="flex flex-col" style={{ height: 'calc(100vh - 230px)', minHeight: 420 }}>
      {/* 对话区 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-4 pr-1">
        {empty && (
          <div className="h-full flex flex-col items-center justify-center text-center px-4">
            <div className="text-4xl mb-3">💬</div>
            <p className="text-sm text-gray-300 font-medium">把我当成坐在你旁边的投资教练</p>
            <p className="text-xs text-gray-500 mt-1 mb-5">回答基于郑希公开采访/季报的真实观点 + 他的方法论，可溯源、不臆造</p>
            <div className="flex flex-col gap-2 w-full max-w-xl">
              {STARTERS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => send(s)}
                  className="text-left text-xs text-gray-300 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5 hover:border-blue-600/60 hover:text-white transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {msgs.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {m.role === 'assistant' && (
              <div className="w-8 h-8 rounded-full bg-blue-600/30 border border-blue-600/50 flex items-center justify-center text-sm shrink-0 mr-2 mt-0.5">郑</div>
            )}
            <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
              m.role === 'user'
                ? 'bg-blue-600 text-white rounded-br-sm'
                : 'bg-gray-900 border border-gray-800 text-gray-200 rounded-bl-sm'
            }`}>
              {m.role === 'assistant' ? (
                <>
                  {m.stocks && m.stocks.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {m.stocks.map(s => {
                        const up = (s.pct ?? 0) > 0, down = (s.pct ?? 0) < 0
                        return (
                          <span
                            key={s.code}
                            className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-gray-800 border border-gray-700"
                            title="已为本轮对话加载实时/技术数据"
                          >
                            <span className="text-gray-300">📎 {s.name}</span>
                            <span className="text-gray-600">{s.code}</span>
                            {s.price != null && (
                              <span className={up ? 'text-red-400' : down ? 'text-green-400' : 'text-gray-400'}>
                                {s.price}（{up ? '+' : ''}{s.pct}%）
                              </span>
                            )}
                            {s.roe != null && (
                              <span className="text-gray-500">ROE {(s.roe * 100).toFixed(1)}%</span>
                            )}
                            {s.pe != null && (
                              <span className="text-gray-500">PE {s.pe.toFixed(0)}</span>
                            )}
                          </span>
                        )
                      })}
                    </div>
                  )}
                  {m.content
                    ? <div className="report-content prose prose-invert prose-sm max-w-none"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>
                    : <span className="text-gray-500 inline-flex items-center gap-1">郑希正在思考<span className="animate-pulse">…</span></span>}
                </>
              ) : (
                <span className="whitespace-pre-wrap">{m.content}</span>
              )}
            </div>
          </div>
        ))}

        {error && <p className="text-xs text-red-400 text-center">{error}</p>}
      </div>

      {/* 输入区 */}
      <div className="pt-3 mt-2 border-t border-gray-800">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) }
            }}
            rows={1}
            placeholder="问点什么…（Enter 发送，Shift+Enter 换行）"
            className="flex-1 resize-none bg-gray-950 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white placeholder-gray-600 focus:border-blue-600 outline-none max-h-32"
          />
          <button
            onClick={() => send(input)}
            disabled={streaming || !input.trim()}
            className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-xl transition-colors shrink-0"
          >
            {streaming ? '回复中…' : '发送'}
          </button>
          {msgs.length > 0 && (
            <button
              onClick={() => { setMsgs([]); setError('') }}
              disabled={streaming}
              title="清空对话"
              className="px-3 py-2.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-gray-400 text-sm rounded-xl transition-colors shrink-0"
            >
              清空
            </button>
          )}
        </div>
        <p className="text-[10px] text-gray-600 mt-1.5 text-center">
          AI 模拟郑希方法论作教学交流，非郑希本人、不代表易方达，<b className="text-gray-500">不构成投资建议、不荐股</b>。
        </p>
      </div>
    </div>
  )
}

// ── 2. 投资方法论 ─────────────────────────────────────────────────────────────

function MethodSection() {
  const [tab, setTab]   = useState<'method' | 'scorecard'>('method')
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  useEffect(() => {
    setLoading(true); setError(''); setText('')
    fetch(`/api/zhengxi/${tab}`)
      .then(async r => {
        if (!r.ok) {
          const e = await r.json().catch(() => ({}))
          throw new Error((e as { detail?: string }).detail || '加载失败')
        }
        return r.json()
      })
      .then(d => setText(d.content ?? ''))
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [tab])

  return (
    <div>
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setTab('method')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium ${tab === 'method' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300 bg-gray-900'}`}
        >📖 投资方法（蒸馏 + 原话佐证）</button>
        <button
          onClick={() => setTab('scorecard')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium ${tab === 'scorecard' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300 bg-gray-900'}`}
        >🎯 六维风格评分卡</button>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        {loading && <div className="text-xs text-gray-500">加载中…</div>}
        {error && <div className="text-xs text-red-400">{error}</div>}
        {!loading && !error && (
          <div className="report-content prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}

// ── 3. 基金风格打分 ───────────────────────────────────────────────────────────

interface FundLite { code: string; name: string }
interface Holding { name: string; code: string; pct: string }
interface Evidence {
  code: string; name: string; type: string
  is_zhengxi: boolean; source: string; quarters_count: number
  latest_quarter?: string; holdings?: Holding[]
  concentration?: number; turnover_proxy?: number
  perf?: { ytd: number; y1: number; y3: number; since: number; max_dd: number }
  scale?: { value: number; date: string }
  ttjj_5dim?: [string, number][]
  cache_key?: string
}

const upd = (v?: number) =>
  v == null ? 'text-gray-300' : v > 0 ? 'text-red-400' : v < 0 ? 'text-emerald-400' : 'text-gray-300'
const pct = (v?: number) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

function ScoreSection() {
  const [funds, setFunds]   = useState<FundLite[]>([])
  const [arg, setArg]       = useState('')
  const [ev, setEv]         = useState<Evidence | null>(null)
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError]   = useState('')

  useEffect(() => {
    fetch('/api/zhengxi/funds').then(r => r.json()).then(d => setFunds(d.funds ?? [])).catch(() => {})
  }, [])

  const run = useCallback(async (code?: string) => {
    const a = (code ?? arg).trim()
    if (!a) return
    setArg(a)
    setLoading(true); setError(''); setEv(null); setReport('')
    try {
      const r = await fetch('/api/zhengxi/fund-evidence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ arg: a }),
      })
      if (!r.ok) {
        const e = await r.json().catch(() => ({}))
        throw new Error((e as { detail?: string }).detail || '准备证据失败')
      }
      const data: Evidence = await r.json()
      setEv(data)
      setLoading(false)

      // SSE 流式评分
      const ck = data.cache_key
      if (!ck) return
      setStreaming(true)
      const sres = await fetch(`/api/zhengxi/fund-score/stream-report?cache_key=${encodeURIComponent(ck)}`)
      if (!sres.ok || !sres.body) { setStreaming(false); return }
      const reader = sres.body.getReader()
      const decoder = new TextDecoder()
      let buffer = '', text = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue
          let chunk: string
          try { chunk = JSON.parse(raw) } catch { chunk = raw }
          if (chunk === '[DONE]') { setStreaming(false); return }
          text += chunk
          setReport(text)
        }
      }
      setStreaming(false)
    } catch (e) {
      setLoading(false); setStreaming(false)
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [arg])

  return (
    <div>
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
        <div className="flex gap-2">
          <input
            value={arg}
            onChange={e => setArg(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && run()}
            placeholder="输入基金代码或名称，如 005827 / 中欧医疗健康"
            className="flex-1 bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-blue-600 outline-none"
          />
          <button
            onClick={() => run()}
            disabled={loading || streaming || !arg.trim()}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {loading ? '准备中…' : '打分'}
          </button>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-gray-500">郑希在管（离线快照，点即评）：</span>
          {funds.map(f => (
            <button
              key={f.code}
              onClick={() => run(f.code)}
              disabled={loading || streaming}
              className="px-2 py-0.5 rounded-full border border-gray-700 text-[11px] text-gray-400 hover:border-blue-600/60 hover:text-blue-300 disabled:opacity-40"
              title={f.name}
            >
              {f.name.length > 12 ? f.name.slice(0, 12) + '…' : f.name}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-gray-600">
          其他基金需联网实时抓取（本机可用）。本评分衡量「与郑希风格的契合度」，<b className="text-gray-500">非基金优劣判断，更非投资建议</b>。
        </p>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-3 text-red-300 text-xs mt-3">{error}</div>
      )}

      {loading && (
        <div className="text-center py-8">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
          <div className="text-xs text-gray-500">正在准备证据档案…</div>
        </div>
      )}

      {ev && (
        <div className="mt-4 space-y-4">
          {/* 证据档案 */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <div className="flex items-center gap-2 flex-wrap mb-3">
              <span className="text-base font-bold text-white">{ev.name}</span>
              <span className="text-xs text-gray-500 font-mono">{ev.code}</span>
              {ev.type && <span className="text-[11px] px-2 py-0.5 rounded bg-gray-800 text-gray-400">{ev.type}</span>}
              <span className={`text-[11px] px-2 py-0.5 rounded ${ev.is_zhengxi ? 'bg-amber-700/40 text-amber-300' : 'bg-gray-800 text-gray-400'}`}>
                {ev.source}
              </span>
              <span className="text-[11px] text-gray-600">披露 {ev.quarters_count} 季</span>
            </div>

            {ev.perf && (
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 mb-3">
                <Stat label="今年以来" value={pct(ev.perf.ytd)} cls={upd(ev.perf.ytd)} />
                <Stat label="近1年"    value={pct(ev.perf.y1)}  cls={upd(ev.perf.y1)} />
                <Stat label="近3年"    value={pct(ev.perf.y3)}  cls={upd(ev.perf.y3)} />
                <Stat label="成立以来"  value={pct(ev.perf.since)} cls={upd(ev.perf.since)} />
                <Stat label="最大回撤"  value={pct(ev.perf.max_dd)} cls="text-emerald-400" />
              </div>
            )}

            <div className="flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-gray-400 mb-3">
              {ev.concentration != null && <span>前十大集中度 <b className="text-gray-200">{ev.concentration}%</b></span>}
              {ev.turnover_proxy != null && <span>换手代理 <b className="text-gray-200">{ev.turnover_proxy}%</b><span className="text-gray-600">（越高越像周期拼接）</span></span>}
              {ev.scale && <span>规模 <b className="text-gray-200">{ev.scale.value}亿</b>（{ev.scale.date}）</span>}
            </div>

            {ev.holdings && ev.holdings.length > 0 && (
              <div>
                <div className="text-[11px] text-gray-500 mb-1.5">最新前十大持仓（{ev.latest_quarter}）</div>
                <div className="flex flex-wrap gap-1.5">
                  {ev.holdings.map((h, i) => (
                    <span key={i} className="text-[11px] px-2 py-0.5 rounded bg-gray-800 text-gray-300">
                      {h.name} <span className="text-gray-500 font-mono">{h.pct}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {ev.ttjj_5dim && ev.ttjj_5dim.length > 0 && (
              <div className="text-[11px] text-gray-500 mt-3">
                天天基金五维：{ev.ttjj_5dim.map(([c, v]) => `${c} ${v}`).join('  ·  ')}
              </div>
            )}
          </div>

          {/* AI 六维评分 */}
          <div className="bg-gray-950/60 border border-blue-900/40 rounded-xl p-5">
            <div className="text-sm font-medium text-blue-300 mb-3 flex items-center gap-2">
              🎯 与郑希风格的契合度（AI 六维评分）
              {streaming && <span className="animate-pulse text-blue-400 text-xs">生成中…</span>}
            </div>
            {report ? (
              <div className="report-content prose prose-invert prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
              </div>
            ) : (
              <div className="text-xs text-gray-600">{streaming ? '' : '等待 AI 评分…'}</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, cls = 'text-gray-200' }: { label: string; value: string; cls?: string }) {
  return (
    <div className="bg-gray-800/50 rounded-lg px-3 py-2">
      <div className="text-[10px] text-gray-500">{label}</div>
      <div className={`text-sm font-mono font-semibold ${cls}`}>{value}</div>
    </div>
  )
}
