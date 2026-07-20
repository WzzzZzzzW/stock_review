import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Activity,
  Check,
  ChevronDown,
  Compass,
  GripHorizontal,
  Landmark,
  LineChart,
  LoaderCircle,
  MessageCircleQuestion,
  Newspaper,
  Plus,
  SendHorizontal,
  ShieldCheck,
  Sparkles,
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  aiAssistantStore,
  useAiAssistant,
  type AssistantContext,
} from '../stores/aiAssistantStore'

interface Props {
  page: string
  phase?: string
}

interface Point {
  x: number
  y: number
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
}

interface DragState {
  kind: 'avatar' | 'panel'
  pointerId: number
  startX: number
  startY: number
  origin: Point
  moved: boolean
}

type CopilotRoleId = 'market' | 'fundamentals' | 'news' | 'technical' | 'sentiment' | 'risk' | 'zhengxi'

interface CopilotRole {
  id: CopilotRoleId
  title: string
  desc: string
  icon: LucideIcon
  accent: string
  iconBg: string
}

const COPILOT_ROLES: CopilotRole[] = [
  { id: 'market', title: '综合决策', desc: '多维证据，给唯一结论', icon: Compass, accent: 'text-blue-300', iconBg: 'bg-blue-500/15' },
  { id: 'fundamentals', title: '财务基本面', desc: '财报质量、估值与护城河', icon: Landmark, accent: 'text-cyan-300', iconBg: 'bg-cyan-500/15' },
  { id: 'news', title: '消息面', desc: '政策事件、新闻映射与预期差', icon: Newspaper, accent: 'text-amber-300', iconBg: 'bg-amber-500/15' },
  { id: 'technical', title: '技术量价', desc: '趋势、量价与支撑压力', icon: LineChart, accent: 'text-violet-300', iconBg: 'bg-violet-500/15' },
  { id: 'sentiment', title: '市场情绪', desc: '广度、赚钱效应与资金偏好', icon: Activity, accent: 'text-rose-300', iconBg: 'bg-rose-500/15' },
  { id: 'risk', title: '风险控制', desc: '仓位、回撤与退出条件', icon: ShieldCheck, accent: 'text-orange-300', iconBg: 'bg-orange-500/15' },
  { id: 'zhengxi', title: '郑希风格', desc: '景气成长、ROE跃迁与客观修正', icon: Sparkles, accent: 'text-emerald-300', iconBg: 'bg-emerald-500/15' },
]

const CHAT_KEY = 'market_copilot_chat_id'
const AVATAR_POS_KEY = 'market_copilot_avatar_position'
const PANEL_POS_KEY = 'market_copilot_panel_position'
const ROLE_KEY = 'market_copilot_role'

function loadRole(): CopilotRoleId {
  const saved = localStorage.getItem(ROLE_KEY) as CopilotRoleId | null
  return COPILOT_ROLES.some(role => role.id === saved) ? saved! : 'market'
}

function loadPoint(key: string, fallback: Point): Point {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '')
    if (Number.isFinite(parsed?.x) && Number.isFinite(parsed?.y)) return parsed
  } catch { /* ignore */ }
  return fallback
}

function clampAvatarToViewport(point: Point): Point {
  return {
    x: Math.max(8, Math.min(point.x, window.innerWidth - 92)),
    y: Math.max(62, Math.min(point.y, window.innerHeight - 96)),
  }
}

function clampPanelToViewport(point: Point): Point {
  const width = Math.min(460, window.innerWidth - 16)
  const height = Math.min(660, window.innerHeight - 78)
  return {
    x: Math.max(8, Math.min(point.x, window.innerWidth - width - 8)),
    y: Math.max(62, Math.min(point.y, window.innerHeight - height - 8)),
  }
}

function pageLabel(page: string) {
  const labels: Record<string, string> = {
    premarket: '盘前作战台',
    intraday: '盘中执行台',
    postmarket: '盘后日档案',
    office: 'AI办公室',
    zhengxi: '郑希投研',
    research: '研究工具',
    strategy: '策略中心',
    watchlist: '自选管理',
  }
  return labels[page] || page || '股票分析'
}

function contextTitle(context: AssistantContext) {
  return context.target?.name
    ? `${pageLabel(context.page)} · ${context.target.name}`
    : pageLabel(context.page)
}

function quickQuestions(context: AssistantContext, roleId: CopilotRoleId): string[] {
  const target = context.target?.name
  const subject = target || '当前市场'
  if (roleId === 'fundamentals') return [`${subject}的财务质量和估值处于什么水平？`, `${subject}最需要核验的基本面风险是什么？`]
  if (roleId === 'news') return [`${subject}今天受哪些消息驱动？`, `${subject}的消息是新催化还是已经被市场消化？`]
  if (roleId === 'technical') return [`${subject}当前量价结构是否支持继续走强？`, `${subject}的支撑、压力和失效条件是什么？`]
  if (roleId === 'sentiment') return [`${subject}的赚钱效应是真扩散还是局部抱团？`, `${subject}当前处于启动、高潮还是退潮？`]
  if (roleId === 'risk') return [`${subject}现在最大的风险敞口是什么？`, `${subject}触发什么条件必须降仓或退出？`]
  if (roleId === 'zhengxi') return [`按郑希的景气成长框架怎么看${subject}？`, `${subject}的景气、ROE和底层逻辑是否在改善？`]
  if (context.target?.type === 'sector' && target) {
    return [
      `${target}现在是真强还是假强？`,
      `${target}的资金、广度和价格为什么不一致？`,
      `${target}对我的持仓和自选有什么影响？`,
    ]
  }
  if (context.target?.type === 'stock' && target) {
    return [
      `${target}当前最重要的多空证据是什么？`,
      `${target}应该保留、降级还是剔除？`,
    ]
  }
  return ['现在市场最重要的矛盾是什么？', '当前资金正在往哪里轮动？', '今天哪些变化会影响我的票？']
}

export default function FloatingMarketAssistant({ page, phase }: Props) {
  const assistant = useAiAssistant()
  const baseContext = useMemo<AssistantContext>(() => ({ page, phase }), [page, phase])
  const [activeContext, setActiveContext] = useState<AssistantContext>(baseContext)
  const [avatarPos, setAvatarPos] = useState<Point>(() => clampAvatarToViewport(loadPoint(AVATAR_POS_KEY, {
    x: Math.max(12, window.innerWidth - 100),
    y: Math.max(76, window.innerHeight - 112),
  })))
  const [panelPos, setPanelPos] = useState<Point>(() => clampPanelToViewport(loadPoint(PANEL_POS_KEY, {
    x: Math.max(8, window.innerWidth - 554),
    y: 74,
  })))
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [chatId, setChatId] = useState('')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [roleId, setRoleId] = useState<CopilotRoleId>(loadRole)
  const [roleMenuOpen, setRoleMenuOpen] = useState(false)
  const dragRef = useRef<DragState | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const roleMenuRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const activeRole = COPILOT_ROLES.find(role => role.id === roleId) || COPILOT_ROLES[0]
  const ActiveRoleIcon = activeRole.icon

  const clampPoint = (kind: DragState['kind'], point: Point): Point => {
    if (kind === 'avatar') {
      return clampAvatarToViewport(point)
    }
    const rect = panelRef.current?.getBoundingClientRect()
    const width = rect?.width || Math.min(460, window.innerWidth - 16)
    const height = rect?.height || Math.min(660, window.innerHeight - 16)
    return {
      x: Math.max(8, Math.min(point.x, window.innerWidth - width - 8)),
      y: Math.max(62, Math.min(point.y, window.innerHeight - height - 8)),
    }
  }

  useEffect(() => {
    const savedId = localStorage.getItem(CHAT_KEY) || ''
    if (!savedId) return
    fetch(`/api/office/chats/${savedId}`)
      .then(async response => response.ok ? response.json() : null)
      .then(chat => {
        if (!chat || !chat.agent_ids?.includes('copilot')) {
          localStorage.removeItem(CHAT_KEY)
          return
        }
        setChatId(chat.id)
        setMessages((chat.messages || []).map((message: { id: string; role: 'user' | 'assistant'; content: string }) => ({
          id: message.id,
          role: message.role,
          content: message.content,
        })))
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const closeRoleMenu = (event: PointerEvent) => {
      if (!roleMenuRef.current?.contains(event.target as Node)) setRoleMenuOpen(false)
    }
    document.addEventListener('pointerdown', closeRoleMenu)
    return () => document.removeEventListener('pointerdown', closeRoleMenu)
  }, [])

  useEffect(() => {
    if (!assistant.request) return
    setActiveContext(assistant.request.context)
    setInput(assistant.request.suggestedQuestion || '')
    setError('')
    window.setTimeout(() => inputRef.current?.focus(), 80)
  }, [assistant.request?.id])

  useEffect(() => {
    if (!assistant.request?.context.target) setActiveContext(baseContext)
  }, [baseContext, assistant.request?.context.target])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, progress, assistant.isOpen])

  useEffect(() => {
    if (!assistant.isOpen || window.innerWidth < 640) return
    const rect = panelRef.current?.getBoundingClientRect()
    if (!rect) return
    const avatarRight = avatarPos.x + 84
    const avatarBottom = avatarPos.y + 90
    const overlaps = avatarPos.x < rect.right && avatarRight > rect.left
      && avatarPos.y < rect.bottom && avatarBottom > rect.top
    if (!overlaps) return
    const next = clampPoint('panel', { x: avatarPos.x - rect.width - 10, y: panelPos.y })
    setPanelPos(next)
    localStorage.setItem(PANEL_POS_KEY, JSON.stringify(next))
  }, [assistant.isOpen, avatarPos.x, avatarPos.y])

  useEffect(() => {
    const onResize = () => {
      setAvatarPos(current => clampPoint('avatar', current))
      setPanelPos(current => clampPoint('panel', current))
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  })

  const beginDrag = (kind: DragState['kind'], event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return
    const origin = kind === 'avatar' ? avatarPos : panelPos
    dragRef.current = {
      kind,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      origin,
      moved: false,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    event.preventDefault()
  }

  const moveDrag = (event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const dx = event.clientX - drag.startX
    const dy = event.clientY - drag.startY
    if (Math.abs(dx) + Math.abs(dy) > 5) drag.moved = true
    const next = clampPoint(drag.kind, { x: drag.origin.x + dx, y: drag.origin.y + dy })
    if (drag.kind === 'avatar') setAvatarPos(next)
    else setPanelPos(next)
  }

  const endDrag = (event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    try { event.currentTarget.releasePointerCapture(event.pointerId) } catch { /* ignore */ }
    if (drag.kind === 'avatar') {
      localStorage.setItem(AVATAR_POS_KEY, JSON.stringify(avatarPos))
      if (!drag.moved) {
        if (assistant.isOpen) aiAssistantStore.close()
        else aiAssistantStore.open(baseContext)
      }
    } else {
      localStorage.setItem(PANEL_POS_KEY, JSON.stringify(panelPos))
    }
    dragRef.current = null
  }

  const newChat = () => {
    setChatId('')
    setMessages([])
    setInput('')
    setProgress('')
    setError('')
    localStorage.removeItem(CHAT_KEY)
    window.setTimeout(() => inputRef.current?.focus(), 50)
  }

  const selectRole = (nextRole: CopilotRoleId) => {
    setRoleId(nextRole)
    setRoleMenuOpen(false)
    localStorage.setItem(ROLE_KEY, nextRole)
    setError('')
    window.setTimeout(() => inputRef.current?.focus(), 50)
  }

  const submit = async (question?: string) => {
    const message = (question ?? input).trim()
    if (!message || loading) return
    setInput('')
    setError('')
    setLoading(true)
    setProgress(`${activeRole.title}正在读取当前页面和实时证据...`)
    setMessages(current => [...current, {
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
    }])

    try {
      const response = await fetch('/api/copilot/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, chat_id: chatId, context: activeContext, role: roleId }),
      })
      if (!response.ok || !response.body) {
        const detail = await response.text()
        throw new Error(detail || 'AI没有返回内容')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let nextChatId = chatId
      let finalResponse = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''
        for (const event of events) {
          if (!event.startsWith('data: ')) continue
          const raw = event.slice(6).trim()
          if (raw === '"[DONE]"') continue
          const payload = JSON.parse(raw)
          if (payload.chat_id) nextChatId = payload.chat_id
          if (payload.type === 'tool_start') setProgress(`正在调用 ${payload.name} 补充证据...`)
          if (payload.type === 'thinking') setProgress('正在比较多维证据并形成结论...')
          if (payload.type === 'final') finalResponse = payload.response || ''
          if (payload.type === 'error') throw new Error(payload.error || 'AI分析失败')
        }
      }
      if (!finalResponse) throw new Error('AI没有生成有效回答')
      if (nextChatId) {
        setChatId(nextChatId)
        localStorage.setItem(CHAT_KEY, nextChatId)
      }
      setMessages(current => [...current, {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: finalResponse,
      }])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'AI分析失败')
    } finally {
      setLoading(false)
      setProgress('')
    }
  }

  const questions = quickQuestions(activeContext, roleId)

  return (
    <>
      <button
        type="button"
        aria-label={`打开${activeRole.title}`}
        title={`Codex 投资助手 · ${activeRole.title}`}
        onPointerDown={event => beginDrag('avatar', event)}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        className={`group fixed z-[80] h-[90px] w-[84px] touch-none select-none focus:outline-none ${assistant.isOpen ? 'hidden sm:block' : ''}`}
        style={{ left: avatarPos.x, top: avatarPos.y }}
      >
        <span className="codex-pet-stage relative flex h-full w-full items-end justify-center">
          <span className="codex-pet-shadow absolute bottom-1 h-3 w-12 rounded-full bg-black/50 blur-[2px]" />
          <img
            src="/assets/codex-pet.png"
            alt=""
            draggable={false}
            className={`codex-pet-image relative z-10 h-[82px] w-[82px] object-contain ${loading ? 'is-thinking' : assistant.isOpen ? 'is-listening' : 'is-idle'}`}
          />
          <span className={`absolute left-0 top-1 z-20 flex h-7 w-7 items-center justify-center rounded-full border border-gray-700 bg-gray-950 shadow-lg ${activeRole.accent}`}>
            <ActiveRoleIcon className="h-4 w-4" />
          </span>
          {loading && (
            <span className="codex-pet-bubble absolute -right-1 top-0 z-20 flex h-7 min-w-9 items-center justify-center gap-1 rounded-full border border-blue-700 bg-gray-950 px-2 shadow-lg">
              <i /><i /><i />
            </span>
          )}
        </span>
      </button>

      {assistant.isOpen && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label="Codex 投资助手对话"
          className="fixed z-[79] flex h-[min(660px,calc(100vh-78px))] w-[min(460px,calc(100vw-16px))] flex-col overflow-hidden rounded-md border border-blue-900/80 bg-gray-950 shadow-2xl shadow-black/60"
          style={{ left: panelPos.x, top: panelPos.y }}
        >
          <header
            className="flex touch-none select-none items-center gap-3 border-b border-gray-800 bg-gray-900 px-3 py-2.5"
            onPointerDown={event => beginDrag('panel', event)}
            onPointerMove={moveDrag}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden">
              <img src="/assets/codex-pet.png" alt="" className="codex-pet-image is-listening h-10 w-10 object-contain" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2"><h2 className="text-sm font-semibold text-white">Codex 投资助手</h2><GripHorizontal className="h-4 w-4 text-gray-700" /></div>
              <p className="truncate text-xs text-gray-500">{contextTitle(activeContext)}</p>
            </div>
            <button
              type="button"
              title="新对话"
              onPointerDown={event => event.stopPropagation()}
              onClick={newChat}
              className="flex h-8 w-8 items-center justify-center rounded text-gray-500 hover:bg-gray-800 hover:text-white"
            ><Plus className="h-4 w-4" /></button>
            <button
              type="button"
              title="关闭"
              onPointerDown={event => event.stopPropagation()}
              onClick={() => aiAssistantStore.close()}
              className="flex h-8 w-8 items-center justify-center rounded text-gray-500 hover:bg-gray-800 hover:text-white"
            ><X className="h-4 w-4" /></button>
          </header>

          <div ref={roleMenuRef} className="relative z-30 border-b border-gray-800 bg-gray-950 px-3 py-2">
            <button
              type="button"
              aria-expanded={roleMenuOpen}
              aria-label="选择分析角色"
              onClick={() => setRoleMenuOpen(open => !open)}
              className="flex w-full items-center gap-2.5 rounded border border-gray-800 bg-gray-900 px-2.5 py-2 text-left hover:border-gray-700 hover:bg-gray-800"
            >
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded ${activeRole.iconBg} ${activeRole.accent}`}>
                <ActiveRoleIcon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-gray-100">{activeRole.title}</span>
                <span className="block truncate text-xs text-gray-500">{activeRole.desc}</span>
              </span>
              <ChevronDown className={`h-4 w-4 text-gray-500 transition-transform ${roleMenuOpen ? 'rotate-180' : ''}`} />
            </button>

            {roleMenuOpen && (
              <div className="absolute left-3 right-3 top-[calc(100%-2px)] z-40 max-h-[360px] overflow-y-auto rounded border border-gray-700 bg-gray-900 py-1 shadow-2xl shadow-black/70">
                {COPILOT_ROLES.map(role => {
                  const RoleIcon = role.icon
                  const selected = role.id === roleId
                  return (
                    <button
                      key={role.id}
                      type="button"
                      onClick={() => selectRole(role.id)}
                      className={`flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-gray-800 ${selected ? 'bg-blue-950/40' : ''}`}
                    >
                      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded ${role.iconBg} ${role.accent}`}>
                        <RoleIcon className="h-4 w-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className={`block text-sm font-medium ${selected ? 'text-blue-200' : 'text-gray-200'}`}>{role.title}</span>
                        <span className="block text-xs text-gray-500">{role.desc}</span>
                      </span>
                      {selected && <Check className="h-4 w-4 shrink-0 text-blue-400" />}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto px-3 py-4">
            {messages.length === 0 && (
              <div className="space-y-4">
                <div className="flex items-start gap-3 text-sm leading-6 text-gray-300">
                  <MessageCircleQuestion className="mt-0.5 h-5 w-5 shrink-0 text-blue-400" />
                  <p><strong className="font-semibold text-white">{activeRole.title}</strong>已接管本轮分析，{activeContext.target?.name ? `并锁定${activeContext.target.name}及其市场证据。` : '已连接当前页面的实时市场证据。'}</p>
                </div>
                <div className="space-y-2">
                  {questions.map(question => (
                    <button key={question} onClick={() => submit(question)} className="block w-full border-l-2 border-gray-700 px-3 py-2 text-left text-sm leading-5 text-gray-400 hover:border-blue-500 hover:bg-gray-900 hover:text-gray-200">
                      {question}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-4">
              {messages.map(message => message.role === 'user' ? (
                <div key={message.id} className="flex justify-end">
                  <div className="max-w-[88%] rounded bg-blue-600 px-3 py-2 text-sm leading-6 text-white">{message.content}</div>
                </div>
              ) : (
                <div key={message.id} className="flex items-start gap-2.5">
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden">
                    <img src="/assets/codex-pet.png" alt="" className="codex-pet-image h-8 w-8 object-contain" />
                  </span>
                  <div className="min-w-0 flex-1 text-sm leading-6 text-gray-300 [&_h1]:mb-2 [&_h1]:font-semibold [&_h1]:text-white [&_h2]:mb-1 [&_h2]:mt-3 [&_h2]:font-semibold [&_h2]:text-blue-200 [&_li]:ml-4 [&_li]:list-disc [&_p]:mb-2 [&_strong]:text-white">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                  </div>
                </div>
              ))}
              {loading && <div className="flex items-center gap-2 text-sm text-blue-300"><LoaderCircle className="h-4 w-4 animate-spin" />{progress}</div>}
              {error && <div className="border-l-2 border-red-700 bg-red-950/20 px-3 py-2 text-sm text-red-300">{error}</div>}
              <div ref={messagesEndRef} />
            </div>
          </div>

          <div className="border-t border-gray-800 bg-gray-900/80 p-3">
            <div className="flex items-end gap-2 rounded border border-gray-700 bg-gray-950 p-2 focus-within:border-blue-600">
              <textarea
                ref={inputRef}
                value={input}
                onChange={event => setInput(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    void submit()
                  }
                }}
                rows={2}
                placeholder="问任何问题，也可结合当前页面"
                className="max-h-28 min-h-[44px] flex-1 resize-none bg-transparent px-1 py-1 text-sm leading-5 text-white outline-none placeholder:text-gray-700"
              />
              <button
                type="button"
                title="发送"
                disabled={!input.trim() || loading}
                onClick={() => submit()}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-blue-600 text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-800 disabled:text-gray-600"
              ><SendHorizontal className="h-4 w-4" /></button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
