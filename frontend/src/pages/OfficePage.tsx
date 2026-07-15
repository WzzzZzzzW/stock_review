/**
 * 🏢 AI 办公室 — 8个交易角色 + 单聊/开会
 */
import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// ── Types ─────────────────────────────────────────────────────────────────────
interface Agent {
  id: string
  title: string
  icon: string
  desc: string
  color: string
}

interface ToolCall {
  name: string
  args: Record<string, unknown>
  result_preview?: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  agent_id: string
  content: string
  is_synthesis: number
  created_at: string
  tool_calls?: ToolCall[]   // 仅在新发送时有；历史从 content 末尾解析
}

interface Chat {
  id: string
  mode: 'single' | 'conference'
  agent_ids: string[]
  title: string
  created_at: string
  updated_at: string
  msg_count: number
  messages?: Message[]
}

// ── 颜色映射 ──────────────────────────────────────────────────────────────────
const COLORS: Record<string, { bg: string; border: string; text: string; ring: string }> = {
  blue:    { bg: 'bg-blue-950/40',    border: 'border-blue-700/50',    text: 'text-blue-300',    ring: 'ring-blue-500' },
  purple:  { bg: 'bg-purple-950/40',  border: 'border-purple-700/50',  text: 'text-purple-300',  ring: 'ring-purple-500' },
  amber:   { bg: 'bg-amber-950/40',   border: 'border-amber-700/50',   text: 'text-amber-300',   ring: 'ring-amber-500' },
  rose:    { bg: 'bg-rose-950/40',    border: 'border-rose-700/50',    text: 'text-rose-300',    ring: 'ring-rose-500' },
  green:   { bg: 'bg-green-950/40',   border: 'border-green-700/50',   text: 'text-green-300',   ring: 'ring-green-500' },
  red:     { bg: 'bg-red-950/40',     border: 'border-red-700/50',     text: 'text-red-300',     ring: 'ring-red-500' },
  orange:  { bg: 'bg-orange-950/40',  border: 'border-orange-700/50',  text: 'text-orange-300',  ring: 'ring-orange-500' },
  cyan:    { bg: 'bg-cyan-950/40',    border: 'border-cyan-700/50',    text: 'text-cyan-300',    ring: 'ring-cyan-500' },
}

// ── 工具调用 → 人话进度文案 ────────────────────────────────────────────────────
const TOOL_LABEL: Record<string, string> = {
  get_stock_snapshot: '查询股票快照',
  get_kline:          '获取K线与技术指标',
  get_financials:     '查询财务数据',
  search_news:        '搜索最新财经新闻',
  get_stock_news:     '查询个股新闻',
  get_my_positions:   '读取你的持仓',
  query_brain:        '检索你的交易脑库',
  get_limitup_today:  '查询今日涨停板',
  get_lhb_today:      '查询龙虎榜资金',
  get_dividend_history: '查询历史分红',
}

// ── 主页面 ────────────────────────────────────────────────────────────────────
export default function OfficePage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [chats, setChats] = useState<Chat[]>([])
  const [activeChat, setActiveChat] = useState<Chat | null>(null)
  const [mode, setMode] = useState<'single' | 'conference'>('single')
  const [selectedAgents, setSelectedAgents] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState('')   // 单聊实时进度文案
  const [streaming, setStreaming] = useState<Message[]>([])   // 会议模式实时流
  const [includeSynthesis, setIncludeSynthesis] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // 加载 agents + 聊天列表
  useEffect(() => {
    fetch('/api/office/agents').then(r => r.json()).then(d => setAgents(d.agents))
    refreshChats()
  }, [])

  const refreshChats = () =>
    fetch('/api/office/chats').then(r => r.json()).then(d => setChats(d.chats ?? []))

  // 自动滚到底
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activeChat?.messages, streaming])

  const openChat = async (chatId: string) => {
    const d = await fetch(`/api/office/chats/${chatId}`).then(r => r.json())
    setActiveChat(d)
    setMode(d.mode)
    setSelectedAgents(d.agent_ids.filter((a: string) => a !== 'trader'))
    setStreaming([])
  }

  const newChat = () => {
    setActiveChat(null)
    setSelectedAgents([])
    setMode('single')
    setStreaming([])
    setInput('')
  }

  const toggleAgent = (id: string) => {
    if (mode === 'single') {
      setSelectedAgents([id])
    } else {
      setSelectedAgents(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
    }
  }

  // ── 发送消息 ──
  const submit = async () => {
    if (!input.trim() || selectedAgents.length === 0 || loading) return
    setLoading(true)
    const msg = input.trim()
    setInput('')

    try {
      if (mode === 'single') {
        await runSingleStream(msg)
      } else {
        // 会议模式 SSE 流式
        await runConference(msg)
      }
    } catch (e) {
      console.error(e)
      alert('请求失败：' + (e as Error).message)
    } finally {
      setLoading(false)
      setProgress('')
    }
  }

  // 单聊：SSE 流式，实时显示"正在查龙虎榜/撰写分析…"进度，结束后载入完整对话
  const runSingleStream = async (msg: string) => {
    setProgress('🤔 正在理解你的问题…')
    const r = await fetch('/api/office/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_id: selectedAgents[0],
        message: msg,
        chat_id: activeChat?.id || '',
      }),
    })
    if (!r.body) throw new Error('无响应流')

    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalChatId = activeChat?.id || ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        if (raw === '"[DONE]"') continue
        try {
          const obj = JSON.parse(raw)
          if (obj.chat_id) finalChatId = obj.chat_id
          if (obj.type === 'tool_start') {
            setProgress(`🔧 正在${TOOL_LABEL[obj.name] || obj.name}…`)
          } else if (obj.type === 'thinking') {
            setProgress('✍️ 正在综合分析、撰写回复…')
          } else if (obj.type === 'error') {
            alert('对话失败：' + obj.error)
          }
        } catch { /* 半包 JSON，忽略 */ }
      }
    }

    if (finalChatId) await openChat(finalChatId)
    refreshChats()
  }

  const runConference = async (question: string) => {
    setStreaming([{
      id: 'user-' + Date.now(),
      role: 'user',
      agent_id: '',
      content: question,
      is_synthesis: 0,
      created_at: new Date().toISOString(),
    }])

    const r = await fetch('/api/office/conference', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        agent_ids: selectedAgents,
        chat_id: activeChat?.id || '',
        include_synthesis: includeSynthesis,
      }),
    })
    if (!r.body) throw new Error('无响应流')

    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalChatId = activeChat?.id || ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        if (raw === '"[DONE]"') continue
        try {
          const obj = JSON.parse(raw)
          if (obj.error) {
            alert('会议失败：' + obj.error)
            continue
          }
          if (obj.chat_id) finalChatId = obj.chat_id
          setStreaming(prev => [...prev, {
            id: 'stream-' + Date.now() + '-' + obj.agent_id,
            role: 'assistant',
            agent_id: obj.agent_id,
            content: obj.content,
            is_synthesis: obj.is_synthesis ? 1 : 0,
            created_at: new Date().toISOString(),
            tool_calls: obj.tool_calls ?? [],
          }])
        } catch {}
      }
    }

    // 会议完成后打开存档
    if (finalChatId) {
      await openChat(finalChatId)
      setStreaming([])
    }
    refreshChats()
  }

  const deleteChat = async (id: string) => {
    if (!confirm('删除这次对话？')) return
    await fetch(`/api/office/chats/${id}`, { method: 'DELETE' })
    if (activeChat?.id === id) newChat()
    refreshChats()
  }

  const agentMap = Object.fromEntries(agents.map(a => [a.id, a]))
  const traderAgent = agentMap['trader']

  const allMessages = activeChat?.messages ?? streaming

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-7xl mx-auto px-4 py-5">
        <div className="grid grid-cols-12 gap-4 min-h-[calc(100vh-120px)]">

          {/* 左侧：聊天历史 */}
          <aside className="col-span-2 space-y-2">
            <button
              onClick={newChat}
              className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-xl font-medium transition-colors"
            >
              + 新对话
            </button>
            <div className="space-y-1 max-h-[calc(100vh-200px)] overflow-y-auto">
              {chats.map(c => (
                <button
                  key={c.id}
                  onClick={() => openChat(c.id)}
                  className={`w-full text-left p-2 rounded-lg text-xs transition-colors group ${
                    activeChat?.id === c.id
                      ? 'bg-gray-700 text-white'
                      : 'bg-gray-900 hover:bg-gray-800 text-gray-400'
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="truncate flex-1">{c.title || '未命名'}</span>
                    <span
                      onClick={e => { e.stopPropagation(); deleteChat(c.id) }}
                      className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 px-1"
                    >×</span>
                  </div>
                  <div className="flex items-center gap-1 mt-1 text-[10px] text-gray-600">
                    <span>{c.mode === 'conference' ? '🗣️ 会议' : '💬 单聊'}</span>
                    <span>·</span>
                    <span>{c.agent_ids.length}人</span>
                  </div>
                </button>
              ))}
              {chats.length === 0 && (
                <p className="text-gray-700 text-xs text-center py-4">还没有对话</p>
              )}
            </div>
          </aside>

          {/* 中间：聊天窗口 */}
          <main className="col-span-7 bg-gray-900/40 border border-gray-800 rounded-2xl flex flex-col overflow-hidden">
            {/* 头部 */}
            <header className="px-5 py-3 border-b border-gray-800 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-white">
                  {activeChat ? activeChat.title : '🏢 AI 办公室'}
                </h2>
                <p className="text-[11px] text-gray-600 mt-0.5">
                  {activeChat
                    ? `${activeChat.mode === 'conference' ? '🗣️ 圆桌会议' : '💬 单聊'} · ${activeChat.agent_ids.length}位参与`
                    : '右侧选择咨询对象 → 单选=单聊, 多选=开会讨论'}
                </p>
              </div>
              {!activeChat && (
                <div className="flex gap-1 bg-gray-800/60 rounded-lg p-0.5">
                  <button
                    onClick={() => { setMode('single'); setSelectedAgents(selectedAgents.slice(0,1)) }}
                    className={`text-xs px-3 py-1.5 rounded-md transition-colors ${mode==='single' ? 'bg-blue-600 text-white' : 'text-gray-500'}`}
                  >💬 单聊</button>
                  <button
                    onClick={() => setMode('conference')}
                    className={`text-xs px-3 py-1.5 rounded-md transition-colors ${mode==='conference' ? 'bg-purple-600 text-white' : 'text-gray-500'}`}
                  >🗣️ 开会</button>
                </div>
              )}
            </header>

            {/* 消息列表 */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {allMessages.length === 0 && !loading && (
                <div className="text-center py-20 space-y-3">
                  <div className="text-5xl">🏢</div>
                  <p className="text-gray-400 text-sm">欢迎来到 AI 办公室</p>
                  <p className="text-gray-600 text-xs max-w-md mx-auto leading-relaxed">
                    8位资深交易角色随时为你提供专业意见。<br/>
                    {mode === 'single'
                      ? '选一位专家直接对话，比如问基本面分析师"PE多少算合理"'
                      : '勾选多位专家召开圆桌会议，他们会各自发言后由首席交易员综合给最终决策'}
                  </p>
                </div>
              )}

              {allMessages.map((m, i) => {
                if (m.role === 'user') return (
                  <div key={m.id} className="flex justify-end">
                    <div className="max-w-[80%] bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
                      {m.content}
                    </div>
                  </div>
                )
                const agent = agentMap[m.agent_id]
                if (!agent) return null
                const c = COLORS[agent.color] ?? COLORS.blue
                return (
                  <div key={m.id} className="space-y-1.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xl">{agent.icon}</span>
                      <span className={`text-sm font-bold ${c.text}`}>{agent.title}</span>
                      {m.is_synthesis === 1 && (
                        <span className="text-[10px] bg-cyan-900/60 text-cyan-300 px-2 py-0.5 rounded-full border border-cyan-800/50">
                          🎯 最终决策
                        </span>
                      )}
                      {/* 工具调用 chip（仅当本次响应实时带回 tool_calls 时） */}
                      {m.tool_calls && m.tool_calls.length > 0 && m.tool_calls.map((tc, j) => (
                        <span
                          key={j}
                          title={JSON.stringify(tc.args)}
                          className="text-[10px] bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full border border-gray-700"
                        >
                          🔧 {tc.name}
                        </span>
                      ))}
                    </div>
                    <div className={`${c.bg} border ${c.border} rounded-2xl rounded-tl-sm px-4 py-3`}>
                      <div className="prose prose-invert prose-sm max-w-none text-gray-200 leading-relaxed">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                      </div>
                    </div>
                  </div>
                )
              })}

              {loading && (
                <div className="flex items-center gap-2 text-gray-400 text-sm">
                  <div className="w-3 h-3 border border-blue-500 border-t-transparent rounded-full animate-spin" />
                  {mode === 'conference'
                    ? '会议进行中…'
                    : (progress || 'AI 思考中…')}
                  {mode !== 'conference' && (
                    <span className="text-gray-600 text-xs">（调动数据分析，约需 30~60 秒，请稍候）</span>
                  )}
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* 输入框 */}
            <div className="p-4 border-t border-gray-800 bg-gray-950/40">
              {selectedAgents.length === 0 && !activeChat && (
                <p className="text-xs text-gray-600 mb-2">👉 请先在右侧选择咨询对象</p>
              )}
              {selectedAgents.length > 0 && (
                <p className="text-[11px] text-gray-500 mb-2">
                  正在与 <span className="text-blue-400">{selectedAgents.map(a => agentMap[a]?.title).join(' · ')}</span>
                  {mode === 'conference' && includeSynthesis && <span className="text-cyan-400"> + 首席交易员(综合)</span>}
                  {' '}对话
                </p>
              )}
              <div className="flex gap-2">
                <textarea
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
                  }}
                  placeholder={
                    selectedAgents.length === 0
                      ? '请先选择咨询对象…'
                      : mode === 'conference'
                      ? '抛出你的问题，多位专家轮流发言…  (⌘ + Enter 发送)'
                      : '随便聊，问什么都行… (⌘ + Enter 发送)'
                  }
                  disabled={selectedAgents.length === 0 || loading}
                  rows={3}
                  className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-600 resize-none focus:border-blue-600 outline-none disabled:opacity-40"
                />
                <button
                  onClick={submit}
                  disabled={!input.trim() || selectedAgents.length === 0 || loading}
                  className="px-5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm font-semibold rounded-xl transition-colors"
                >
                  发送
                </button>
              </div>
              {mode === 'conference' && !activeChat && (
                <label className="flex items-center gap-2 mt-2 text-xs text-gray-500">
                  <input
                    type="checkbox"
                    checked={includeSynthesis}
                    onChange={e => setIncludeSynthesis(e.target.checked)}
                    className="w-3.5 h-3.5 accent-cyan-500"
                  />
                  会议结束让首席交易员综合所有意见给最终决策
                </label>
              )}
            </div>
          </main>

          {/* 右侧：Agent 选择 */}
          <aside className="col-span-3 space-y-2 max-h-[calc(100vh-120px)] overflow-y-auto">
            <h3 className="text-xs text-gray-500 font-semibold uppercase tracking-wider mb-2 px-1">
              {activeChat ? '本次对话参与者' : (mode === 'single' ? '选一位专家' : '勾选与会者')}
            </h3>
            {agents.map(a => {
              const c = COLORS[a.color] ?? COLORS.blue
              const selected = selectedAgents.includes(a.id)
              const inActive = activeChat?.agent_ids.includes(a.id)
              const disabled = !!activeChat && !inActive
              const highlight = activeChat ? inActive : selected
              return (
                <button
                  key={a.id}
                  onClick={() => !activeChat && a.id !== 'trader' && toggleAgent(a.id)}
                  disabled={disabled || a.id === 'trader'}
                  className={`w-full text-left p-3 rounded-xl border transition-all ${
                    highlight
                      ? `${c.bg} ${c.border} ring-2 ${c.ring}`
                      : 'bg-gray-900 border-gray-800 hover:border-gray-700'
                  } ${(disabled || a.id === 'trader') && !highlight ? 'opacity-40' : ''}`}
                >
                  <div className="flex items-start gap-2.5">
                    <span className="text-2xl shrink-0">{a.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className={`text-sm font-semibold ${c.text}`}>{a.title}</span>
                      </div>
                      <p className="text-[11px] text-gray-500 mt-0.5 leading-relaxed">{a.desc}</p>
                    </div>
                    {a.id === 'trader' && (
                      <span className="text-[10px] text-cyan-400 shrink-0">自动召集</span>
                    )}
                  </div>
                </button>
              )
            })}
            {traderAgent && (
              <p className="text-[10px] text-gray-700 px-1 pt-1 leading-relaxed">
                💡 <b>首席交易员</b>只在<b>开会模式</b>且勾选了「综合决策」时自动出场
              </p>
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}
