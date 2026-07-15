/**
 * 交易脑库 — 个人交易知识库
 * 喂入任意内容 → AI提炼规则 → 持续进化的交易系统
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

// ── Types ─────────────────────────────────────────────────────────────────────
interface Rule {
  id: string
  source_id: string
  category: string
  rule: string
  conditions: string[]
  tags: string[]
  time_frame: string
  confidence: number
  times_matched: number
  validated_win: number
  validated_loss: number
  created_at: string
}

interface Source {
  id: string
  content: string
  source_type: string
  title: string
  created_at: string
  rule_count: number
}

interface PlaybookItem {
  id: string
  category: string
  title: string
  content: string
  rule_ids: string[]
  generated_at: string
}

// ── 常量 ──────────────────────────────────────────────────────────────────────
const CATEGORIES: Record<string, { label: string; color: string; bg: string }> = {
  entry:      { label: '买入信号', color: 'text-green-400',  bg: 'bg-green-950/40 border-green-800/50' },
  exit:       { label: '卖出信号', color: 'text-red-400',    bg: 'bg-red-950/40 border-red-800/50' },
  risk:       { label: '风险控制', color: 'text-orange-400', bg: 'bg-orange-950/40 border-orange-800/50' },
  sector:     { label: '板块逻辑', color: 'text-blue-400',   bg: 'bg-blue-950/40 border-blue-800/50' },
  macro:      { label: '宏观判断', color: 'text-purple-400', bg: 'bg-purple-950/40 border-purple-800/50' },
  psychology: { label: '心理纪律', color: 'text-yellow-400', bg: 'bg-yellow-950/40 border-yellow-800/50' },
  pattern:    { label: '技术形态', color: 'text-cyan-400',   bg: 'bg-cyan-950/40 border-cyan-800/50' },
  other:      { label: '其他',     color: 'text-gray-400',   bg: 'bg-gray-800/40 border-gray-700/50' },
}

const SOURCE_TYPES = [
  { value: 'manual',       label: '💬 随手记录' },
  { value: 'trade_review', label: '📊 复盘总结' },
  { value: 'article',      label: '📰 帖子/文章' },
  { value: 'book',         label: '📚 书摘笔记' },
]

function confidenceBar(c: number) {
  const pct = Math.round(c * 100)
  const color = c >= 0.8 ? 'bg-green-500' : c >= 0.65 ? 'bg-blue-500' : c >= 0.5 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-gray-500">{pct}%</span>
    </div>
  )
}

// ── 每日自动导入面板 ──────────────────────────────────────────────────────────
interface AutoRun {
  ok: boolean
  at?: string
  fetched?: number
  new_items?: number
  docs_created?: number
  rules_added?: number
  by_bucket?: Record<string, { label: string; docs: number; rules: number; items: number }>
  message?: string
}
interface AutoStatus {
  running: boolean
  progress: string
  last_run: AutoRun | null
  total_imported: number
}

interface RssFeed { url: string; name: string }

function AutoImportPanel({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState<AutoStatus | null>(null)
  const [running, setRunning] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // RSS 源管理
  const [showFeeds, setShowFeeds] = useState(false)
  const [feeds, setFeeds] = useState<RssFeed[]>([])
  const [newUrl, setNewUrl] = useState('')
  const [newName, setNewName] = useState('')
  const [feedMsg, setFeedMsg] = useState('')
  const [adding, setAdding] = useState(false)

  const load = async () => {
    try {
      const r = await fetch('/api/brain/auto-import/status')
      const d: AutoStatus = await r.json()
      setStatus(d)
      return d
    } catch { return null }
  }

  const loadFeeds = async () => {
    try {
      const r = await fetch('/api/brain/auto-import/feeds')
      const d = await r.json()
      setFeeds(d.feeds ?? [])
    } catch {}
  }

  const addFeed = async () => {
    if (!newUrl.trim()) return
    setAdding(true)
    setFeedMsg('')
    try {
      const r = await fetch('/api/brain/auto-import/feeds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: newUrl.trim(), name: newName.trim() }),
      })
      const d = await r.json()
      if (!r.ok) { setFeedMsg(d.detail || '添加失败'); setAdding(false); return }
      setFeeds(d.feeds ?? [])
      setFeedMsg(`✅ 已添加，实测拉到 ${d.fetched} 条`)
      setNewUrl(''); setNewName('')
    } catch {
      setFeedMsg('请求失败')
    }
    setAdding(false)
  }

  const removeFeed = async (url: string) => {
    try {
      const r = await fetch(`/api/brain/auto-import/feeds?url=${encodeURIComponent(url)}`, { method: 'DELETE' })
      const d = await r.json()
      setFeeds(d.feeds ?? [])
    } catch {}
  }

  useEffect(() => {
    load()
    loadFeeds()
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const trigger = async () => {
    setRunning(true)
    try {
      await fetch('/api/brain/auto-import/run', { method: 'POST' })
    } catch {}
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      const d = await load()
      if (d && !d.running) {
        if (pollRef.current) clearInterval(pollRef.current)
        setRunning(false)
        onDone()
      }
    }, 1500)
  }

  const lr = status?.last_run
  const busy = running || status?.running

  return (
    <div className="bg-gradient-to-br from-indigo-950/40 to-gray-900/60 border border-indigo-800/40 rounded-2xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">🤖 每日自动导入</span>
            {status != null && (
              <span className="text-[10px] text-indigo-300 bg-indigo-950/60 border border-indigo-800/50 px-2 py-0.5 rounded-full shrink-0">
                累计 {status.total_imported} 条已消化
              </span>
            )}
          </div>
          <p className="text-[11px] text-gray-500 mt-1 leading-relaxed">
            每天 18:30 自动从 <span className="text-gray-400">财联社 / 东财 / 同花顺 / 富途 / 新浪 / 央视 / 研报</span> 抓取，打包提炼成题材·资金·宏观规则入库（自动去重）
          </p>
        </div>
        <button
          onClick={trigger}
          disabled={busy}
          className="px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition-colors shrink-0 whitespace-nowrap"
        >
          {busy ? '导入中…' : '⚡ 立即导入'}
        </button>
      </div>

      {busy && status?.progress && (
        <div className="flex items-center gap-2 text-[11px] text-indigo-300">
          <div className="w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
          {status.progress}
        </div>
      )}

      {!busy && lr && (
        <div className="border-t border-indigo-900/40 pt-2.5 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className={`text-xs font-medium ${lr.ok ? 'text-green-400' : 'text-red-400'}`}>
              {lr.ok ? '✅' : '⚠️'} {lr.message}
            </span>
            {lr.at && <span className="text-[10px] text-gray-600">{lr.at.replace('T', ' ')}</span>}
          </div>
          {lr.by_bucket && Object.keys(lr.by_bucket).length > 0 && (
            <div className="flex gap-1.5 flex-wrap">
              {Object.entries(lr.by_bucket).map(([k, v]) => (
                <span key={k} className="text-[10px] text-gray-400 bg-gray-800/60 px-2 py-0.5 rounded-full">
                  {v.label} · {v.items}条→{v.rules}规则
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* RSS 源管理 */}
      <div className="border-t border-indigo-900/40 pt-2">
        <button
          onClick={() => setShowFeeds(s => !s)}
          className="text-[11px] text-indigo-300 hover:text-indigo-200 transition-colors"
        >
          {showFeeds ? '▾' : '▸'} 管理 RSS 源（{feeds.length}）
        </button>

        {showFeeds && (
          <div className="mt-2 space-y-2">
            {feeds.map(f => (
              <div key={f.url} className="flex items-center gap-2 bg-gray-900/60 border border-gray-800 rounded-lg px-2.5 py-1.5">
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-300 truncate">{f.name}</p>
                  <p className="text-[10px] text-gray-600 truncate">{f.url}</p>
                </div>
                <button
                  onClick={() => removeFeed(f.url)}
                  className="text-gray-600 hover:text-red-400 transition-colors text-sm shrink-0"
                  title="删除"
                >✕</button>
              </div>
            ))}

            <div className="space-y-1.5 pt-1">
              <input
                value={newUrl}
                onChange={e => setNewUrl(e.target.value)}
                placeholder="RSS 链接，如 https://36kr.com/feed"
                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-600 focus:border-indigo-600 outline-none"
              />
              <div className="flex gap-1.5">
                <input
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  placeholder="名称（可选）"
                  className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-600 focus:border-indigo-600 outline-none"
                />
                <button
                  onClick={addFeed}
                  disabled={adding || !newUrl.trim()}
                  className="px-3 py-1.5 bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-colors shrink-0"
                >
                  {adding ? '校验中…' : '＋ 添加'}
                </button>
              </div>
              {feedMsg && <p className="text-[10px] text-gray-400">{feedMsg}</p>}
              <p className="text-[10px] text-gray-600">
                提示：雪球/公众号长文需自建 RSSHub 后填入；公共 rsshub.app 常被限流
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── 喂入面板 ──────────────────────────────────────────────────────────────────
function FeedPanel({ onDone }: { onDone: () => void }) {
  const [content, setContent] = useState('')
  const [sourceType, setSourceType] = useState('article')
  const [title, setTitle] = useState('')
  const [state, setState] = useState<'idle' | 'loading' | 'polling' | 'done' | 'error' | 'ocr'>('idle')
  const [sourceId, setSourceId] = useState('')
  const [ruleCount, setRuleCount] = useState(0)
  const [errMsg, setErrMsg] = useState('')
  const [ocrPreview, setOcrPreview] = useState('')  // 显示从图片识别的源
  const fileRef = useRef<HTMLInputElement>(null)
  const dropRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)

  // ── OCR 处理 ──
  const handleImage = async (file: File) => {
    if (!file.type.startsWith('image/')) {
      setErrMsg('请上传图片文件')
      return
    }
    setState('ocr')
    setErrMsg('')
    setOcrPreview(file.name)

    const fd = new FormData()
    fd.append('file', file)
    fd.append('title', title || file.name)
    fd.append('source_type', sourceType)
    fd.append('auto_extract', 'false')  // 先返回 OCR 文本，让用户校对

    try {
      const r = await fetch('/api/brain/feed-image', { method: 'POST', body: fd })
      const d = await r.json()
      if (!r.ok) {
        setErrMsg(d.detail || 'OCR 识别失败')
        setState('idle')
        return
      }
      // 把识别的文本填入 textarea，让用户校对
      setContent(d.ocr_text)
      if (!title) setTitle(`📷 ${file.name}`)
      setState('idle')
    } catch (e) {
      setErrMsg('OCR 请求失败：' + (e as Error).message)
      setState('idle')
    }
  }

  const onFilePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) handleImage(f)
  }
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleImage(f)
  }
  const onPaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile()
        if (file) {
          e.preventDefault()
          handleImage(file)
          return
        }
      }
    }
  }

  const submit = async () => {
    if (content.trim().length < 20) return
    setState('loading')
    try {
      const r = await fetch('/api/brain/feed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, source_type: sourceType, title }),
      })
      const d = await r.json()
      setSourceId(d.source_id)
      setState('polling')
    } catch {
      setState('error')
      setErrMsg('提交失败，请检查后端服务')
    }
  }

  // 轮询提炼状态
  useEffect(() => {
    if (state !== 'polling' || !sourceId) return
    const timer = setInterval(async () => {
      try {
        const r = await fetch(`/api/brain/feed/status/${sourceId}`)
        const d = await r.json()
        if (d.status === 'done') {
          setRuleCount(d.rule_count)
          setState('done')
          clearInterval(timer)
          setTimeout(onDone, 1500)
        } else if (d.status === 'error') {
          setErrMsg(d.error)
          setState('error')
          clearInterval(timer)
        }
      } catch {}
    }, 1500)
    return () => clearInterval(timer)
  }, [state, sourceId, onDone])

  const reset = () => {
    setState('idle')
    setContent('')
    setTitle('')
    setSourceId('')
    setRuleCount(0)
    setErrMsg('')
    setOcrPreview('')
  }

  if (state === 'done') return (
    <div className="text-center py-8 space-y-3">
      <div className="text-4xl">✅</div>
      <p className="text-white font-semibold">成功提炼 {ruleCount} 条规则</p>
      <p className="text-gray-500 text-sm">已存入你的交易脑库</p>
      <button onClick={reset} className="text-xs text-blue-400 border border-blue-800 px-4 py-2 rounded-xl hover:bg-blue-950/30 transition-colors">
        继续输入
      </button>
    </div>
  )

  if (state === 'loading' || state === 'polling' || state === 'ocr') return (
    <div className="text-center py-8 space-y-4">
      <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
      <p className="text-blue-400 text-sm">
        {state === 'ocr'    ? '📷 正在识别图片文字…'
         : state === 'loading' ? '提交中…'
         : 'AI 正在提炼交易规则…'}
      </p>
      <p className="text-gray-600 text-xs">
        {state === 'ocr' ? '通常需要 3-8 秒' : '通常需要 5-15 秒'}
      </p>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* 类型选择 */}
      <div className="flex gap-2 flex-wrap">
        {SOURCE_TYPES.map(t => (
          <button
            key={t.value}
            onClick={() => setSourceType(t.value)}
            className={`text-xs px-3 py-1.5 rounded-xl border transition-colors ${
              sourceType === t.value
                ? 'bg-blue-600/30 border-blue-600 text-blue-300'
                : 'bg-gray-900 border-gray-700 text-gray-500 hover:border-gray-600'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 标题（可选） */}
      <input
        value={title}
        onChange={e => setTitle(e.target.value)}
        placeholder="标题/来源（可选，方便以后查找）"
        className="w-full bg-gray-900 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white placeholder-gray-600 focus:border-blue-600 outline-none"
      />

      {/* 📷 图片上传（OCR） */}
      <div
        ref={dropRef}
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => fileRef.current?.click()}
        className={`border-2 border-dashed rounded-xl px-4 py-3 cursor-pointer transition-all ${
          dragging
            ? 'border-blue-500 bg-blue-950/30'
            : 'border-gray-700 hover:border-gray-600 bg-gray-900/40'
        }`}
      >
        <div className="flex items-center gap-3">
          <span className="text-2xl">📷</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-gray-300 font-medium">
              {ocrPreview ? `✅ 已识别: ${ocrPreview}` : '上传/拖拽/粘贴 文章截图'}
            </p>
            <p className="text-[11px] text-gray-600 mt-0.5">
              支持手机/电脑截图 · 自动 OCR 识别文字后填入下方文本框，你可以校对编辑再提交
            </p>
          </div>
          <span className="text-xs text-blue-400 shrink-0">点击选择 →</span>
        </div>
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onFilePick} />
      </div>

      {/* 正文 */}
      <textarea
        value={content}
        onChange={e => setContent(e.target.value)}
        onPaste={onPaste}
        placeholder={`粘贴文字内容、拖图片到上方区域、或直接 Ctrl+V 粘贴截图都可以：\n• 论坛帖子的复盘分析\n• 你看到的精彩股评/操作逻辑\n• 自己交易后的总结\n• 书里的某段话\n• 脑子里突然冒出来的想法\n\nAI 会自动提炼出可操作的交易规则存入脑库`}
        rows={10}
        className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-600 resize-none focus:border-blue-600 outline-none leading-relaxed"
      />

      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-600">
          {content.length} 字{ocrPreview && content && <span className="text-blue-500 ml-2">· 来自图片识别</span>}
        </div>
        <button
          onClick={submit}
          disabled={content.trim().length < 20}
          className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-xl text-sm font-semibold transition-colors"
        >
          🧠 提炼入库
        </button>
      </div>

      {state === 'error' && (
        <p className="text-red-400 text-xs text-center">{errMsg}</p>
      )}
    </div>
  )
}

// ── 规则卡片 ──────────────────────────────────────────────────────────────────
function RuleCard({ rule, onDelete, onValidate, onUnvalidate }: {
  rule: Rule
  onDelete: (id: string) => void
  onValidate: (id: string, win: boolean) => void
  onUnvalidate: (id: string, win: boolean) => void
}) {
  const cat = CATEGORIES[rule.category] ?? CATEGORIES.other
  const totalValidated = rule.validated_win + rule.validated_loss

  return (
    <div className={`rounded-xl border p-3.5 space-y-2.5 ${cat.bg}`}>
      <div className="flex items-start justify-between gap-2">
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${cat.bg} ${cat.color}`}>
          {cat.label}
        </span>
        <div className="flex gap-1.5">
          {/* 验证按钮 */}
          <button
            onClick={() => onValidate(rule.id, true)}
            className="text-[10px] px-2 py-1 bg-green-950/60 hover:bg-green-900/60 text-green-400 border border-green-800/50 rounded-lg transition-colors"
            title="这条规则帮我赚钱了"
          >✓ 有效</button>
          <button
            onClick={() => onValidate(rule.id, false)}
            className="text-[10px] px-2 py-1 bg-red-950/60 hover:bg-red-900/60 text-red-400 border border-red-800/50 rounded-lg transition-colors"
            title="这条规则让我亏钱了"
          >✗ 无效</button>
          <button
            onClick={() => onDelete(rule.id)}
            className="text-[10px] px-2 py-1 bg-gray-800/60 hover:bg-gray-700/60 text-gray-500 border border-gray-700/50 rounded-lg transition-colors"
          >删除</button>
        </div>
      </div>

      {/* 规则正文 */}
      <p className="text-sm text-white leading-relaxed">{rule.rule}</p>

      {/* 条件 */}
      {rule.conditions.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {rule.conditions.map((c, i) => (
            <span key={i} className="text-[10px] text-gray-400 bg-gray-800/60 px-2 py-0.5 rounded-full">
              {c}
            </span>
          ))}
        </div>
      )}

      {/* 底部元信息 */}
      <div className="flex items-center justify-between pt-0.5">
        <div className="flex items-center gap-3">
          {confidenceBar(rule.confidence)}
          {rule.time_frame && (
            <span className="text-[10px] text-gray-600">{rule.time_frame}</span>
          )}
        </div>
        <div className="flex gap-2 text-[10px] text-gray-600">
          {totalValidated > 0 && (
            <span>
              验证{' '}
              {rule.validated_win > 0 ? (
                <button
                  type="button"
                  onClick={() => onUnvalidate(rule.id, true)}
                  title="点击撤回一次「有效」"
                  className="text-green-500 hover:text-green-300 hover:underline cursor-pointer"
                >
                  {rule.validated_win}✓
                </button>
              ) : (
                <span className="text-green-500">{rule.validated_win}✓</span>
              )}{' '}
              {rule.validated_loss > 0 ? (
                <button
                  type="button"
                  onClick={() => onUnvalidate(rule.id, false)}
                  title="点击撤回一次「无效」"
                  className="text-red-500 hover:text-red-300 hover:underline cursor-pointer"
                >
                  {rule.validated_loss}✗
                </button>
              ) : (
                <span className="text-red-500">{rule.validated_loss}✗</span>
              )}
            </span>
          )}
          {rule.times_matched > 0 && <span>匹配{rule.times_matched}次</span>}
        </div>
      </div>
    </div>
  )
}

// ── Playbook面板 ──────────────────────────────────────────────────────────────
function PlaybookPanel() {
  const [genStatus, setGenStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const qc = useQueryClient()

  const { data } = useQuery<{ playbook: PlaybookItem[] }>({
    queryKey: ['brain-playbook'],
    queryFn: () => fetch('/api/brain/playbook').then(r => r.json()),
    staleTime: 5 * 60 * 1000,
  })

  const playbook = data?.playbook ?? []

  const regenerate = async () => {
    setGenStatus('loading')
    try {
      await fetch('/api/brain/playbook/regenerate', { method: 'POST' })
      // 轮询
      const poll = setInterval(async () => {
        const r = await fetch('/api/brain/playbook/status')
        const d = await r.json()
        if (d.status === 'done') {
          clearInterval(poll)
          setGenStatus('done')
          qc.invalidateQueries({ queryKey: ['brain-playbook'] })
        } else if (d.status === 'error') {
          clearInterval(poll)
          setGenStatus('error')
        }
      }, 2000)
    } catch {
      setGenStatus('error')
    }
  }

  if (playbook.length === 0) return (
    <div className="text-center py-12 space-y-4">
      <div className="text-4xl">📖</div>
      <p className="text-gray-400 text-sm">Playbook 还没有生成</p>
      <p className="text-gray-600 text-xs">积累了一定规则后，点击生成属于你的交易系统手册</p>
      <button
        onClick={regenerate}
        disabled={genStatus === 'loading'}
        className="px-5 py-2.5 bg-purple-600/30 hover:bg-purple-600/50 text-purple-400 border border-purple-700/50 rounded-xl text-sm transition-colors disabled:opacity-40"
      >
        {genStatus === 'loading' ? '生成中…' : '✨ 生成 Playbook'}
      </button>
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">根据你的脑库规则归纳生成</p>
        <button
          onClick={regenerate}
          disabled={genStatus === 'loading'}
          className="text-xs text-purple-400 border border-purple-800 px-3 py-1.5 rounded-xl hover:bg-purple-950/30 transition-colors disabled:opacity-40"
        >
          {genStatus === 'loading' ? '更新中…' : '🔄 重新生成'}
        </button>
      </div>

      {playbook.map(item => {
        const cat = CATEGORIES[item.category] ?? CATEGORIES.other
        return (
          <div key={item.id} className={`rounded-xl border p-4 space-y-3 ${cat.bg}`}>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-bold ${cat.color}`}>{cat.label || item.category}</span>
              <span className="text-sm font-semibold text-white">{item.title}</span>
            </div>
            <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">{item.content}</p>
            {item.rule_ids.length > 0 && (
              <p className="text-[10px] text-gray-600">基于 {item.rule_ids.length} 条规则归纳</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── 来源历史 ──────────────────────────────────────────────────────────────────
const SOURCE_TYPE_LABEL: Record<string, string> = {
  manual: '随手记录', trade_review: '复盘总结', article: '帖子/文章', book: '书摘笔记',
  auto_news: '🤖 自动·快讯', auto_policy: '🤖 自动·政策', auto_research: '🤖 自动·研报',
  auto_article: '🤖 自动·深度长文',
}

function SourceDetailModal({ source, onClose }: { source: Source; onClose: () => void }) {
  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // 这条来源提炼出的具体规则
  const { data: rulesData, isLoading: rulesLoading } = useQuery<{ rules: Rule[] }>({
    queryKey: ['brain-source-rules', source.id],
    queryFn: () => fetch(`/api/brain/sources/${source.id}/rules`).then(r => r.json()),
    staleTime: 30_000,
  })
  const rules = rulesData?.rules ?? []

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-start justify-between gap-3 p-5 border-b border-gray-800 shrink-0">
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold text-white break-words">{source.title || '未命名来源'}</h3>
            <div className="flex items-center gap-2 flex-wrap mt-2">
              <span className="text-[10px] text-gray-400 bg-gray-800 px-2 py-0.5 rounded-full">
                {SOURCE_TYPE_LABEL[source.source_type] ?? source.source_type}
              </span>
              {source.rule_count > 0 && (
                <span className="text-[10px] text-blue-400 bg-blue-950/40 border border-blue-800/50 px-2 py-0.5 rounded-full">
                  提炼 {source.rule_count} 条规则
                </span>
              )}
              <span className="text-[10px] text-gray-600">{new Date(source.created_at).toLocaleString('zh-CN')}</span>
              <span className="text-[10px] text-gray-700">· 共 {source.content.length} 字</span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white hover:bg-gray-800 rounded-lg w-8 h-8 flex items-center justify-center shrink-0 transition-colors"
            title="关闭（Esc）"
          >✕</button>
        </div>
        {/* 正文：先看提炼出的规则，再看原文 */}
        <div className="p-5 overflow-y-auto space-y-5">
          {/* 提炼出的具体规则 */}
          <div>
            <h4 className="text-xs font-semibold text-gray-300 mb-2.5 flex items-center gap-2">
              🧩 提炼出的规则
              <span className="text-[10px] text-gray-600 font-normal">
                {rulesLoading ? '加载中…' : `现存 ${rules.length} 条${
                  source.rule_count > rules.length ? `（提炼时 ${source.rule_count} 条，部分已删除）` : ''
                }`}
              </span>
            </h4>
            {rulesLoading ? (
              <p className="text-xs text-gray-600">加载中…</p>
            ) : rules.length === 0 ? (
              <p className="text-xs text-gray-600 bg-gray-800/40 border border-gray-800 rounded-xl p-3">
                这条来源没有提炼出规则（内容太碎/太短），或提炼出的规则已被全部删除。
              </p>
            ) : (
              <div className="space-y-2">
                {rules.map(r => {
                  const cat = CATEGORIES[r.category] ?? CATEGORIES.other
                  return (
                    <div key={r.id} className={`rounded-xl border p-3 ${cat.bg}`}>
                      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                        <span className={`text-[10px] font-medium ${cat.color}`}>{cat.label}</span>
                        {r.time_frame && <span className="text-[10px] text-gray-500">{r.time_frame}</span>}
                        <div className="ml-auto">{confidenceBar(r.confidence)}</div>
                      </div>
                      <p className="text-sm text-gray-200 leading-relaxed">{r.rule}</p>
                      {r.conditions.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {r.conditions.map((c, i) => (
                            <span key={i} className="text-[10px] text-gray-400 bg-gray-800/60 px-1.5 py-0.5 rounded">
                              {c}
                            </span>
                          ))}
                        </div>
                      )}
                      {r.tags.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {r.tags.map((t, i) => (
                            <span key={i} className="text-[10px] text-blue-400/80">#{t}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* 原文 */}
          <div>
            <h4 className="text-xs font-semibold text-gray-300 mb-2.5">📄 原文</h4>
            <p className="text-sm text-gray-400 leading-relaxed whitespace-pre-wrap break-words">{source.content}</p>
          </div>
        </div>
      </div>
    </div>
  )
}

function SourcesPanel({ onDeleted }: { onDeleted: () => void }) {
  const { data, refetch } = useQuery<{ sources: Source[] }>({
    queryKey: ['brain-sources'],
    queryFn: () => fetch('/api/brain/sources').then(r => r.json()),
    staleTime: 30_000,
  })

  const sources = data?.sources ?? []
  const [selected, setSelected] = useState<Source | null>(null)

  const deleteSource = async (id: string) => {
    await fetch(`/api/brain/sources/${id}`, { method: 'DELETE' })
    refetch()
    onDeleted()
  }

  const typeLabel = SOURCE_TYPE_LABEL

  if (sources.length === 0) return (
    <div className="text-center py-12 text-gray-600 text-sm">还没有输入过内容</div>
  )

  return (
    <div className="space-y-2">
      {sources.map(s => (
        <div
          key={s.id}
          onClick={() => setSelected(s)}
          className="bg-gray-900/60 border border-gray-800 hover:border-gray-600 hover:bg-gray-900 rounded-xl p-3.5 space-y-2 cursor-pointer transition-colors"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                {s.title && <span className="text-sm font-medium text-white truncate">{s.title}</span>}
                <span className="text-[10px] text-gray-600 bg-gray-800 px-2 py-0.5 rounded-full shrink-0">
                  {typeLabel[s.source_type] ?? s.source_type}
                </span>
                {s.rule_count > 0 && (
                  <span className="text-[10px] text-blue-400 bg-blue-950/40 border border-blue-800/50 px-2 py-0.5 rounded-full shrink-0">
                    提炼 {s.rule_count} 条规则
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-500 mt-1 line-clamp-2">{s.content.slice(0, 120)}…</p>
              <p className="text-[10px] text-blue-500/70 mt-1">点击查看全文 →</p>
            </div>
            <button
              onClick={e => { e.stopPropagation(); deleteSource(s.id) }}
              className="text-gray-700 hover:text-red-400 transition-colors text-sm shrink-0"
            >✕</button>
          </div>
          <p className="text-[10px] text-gray-700">{new Date(s.created_at).toLocaleString('zh-CN')}</p>
        </div>
      ))}

      {selected && <SourceDetailModal source={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────
type Tab = 'feed' | 'rules' | 'playbook' | 'sources'

export default function BrainPage() {
  const [tab, setTab] = useState<Tab>('feed')
  const [catFilter, setCatFilter] = useState('')
  const qc = useQueryClient()

  const { data: statsData } = useQuery({
    queryKey: ['brain-stats'],
    queryFn: () => fetch('/api/brain/stats').then(r => r.json()),
    staleTime: 10_000,
    refetchInterval: 15_000,
  })

  const { data: rulesData, refetch: refetchRules } = useQuery<{ rules: Rule[]; counts: Record<string, number>; total: number }>({
    queryKey: ['brain-rules', catFilter],
    queryFn: () => fetch(`/api/brain/rules${catFilter ? `?category=${catFilter}` : ''}`).then(r => r.json()),
    staleTime: 10_000,
  })

  const rules = rulesData?.rules ?? []
  const counts = rulesData?.counts ?? {}
  const stats = statsData ?? { total_rules: 0, total_sources: 0, has_playbook: false }

  // ── 撤销提示条：误点「有效/无效/删除」后 6 秒内可一键撤回 ──────────────────
  const [undo, setUndo] = useState<{ text: string; run: () => Promise<void> } | null>(null)
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showUndo = (text: string, run: () => Promise<void>) => {
    if (undoTimer.current) clearTimeout(undoTimer.current)
    setUndo({ text, run })
    undoTimer.current = setTimeout(() => setUndo(null), 6000)
  }

  const doUndo = async () => {
    if (!undo) return
    if (undoTimer.current) clearTimeout(undoTimer.current)
    const run = undo.run
    setUndo(null)
    await run()
    refetchRules()
    qc.invalidateQueries({ queryKey: ['brain-stats'] })
  }

  const deleteRule = async (id: string) => {
    const r = rules.find(x => x.id === id)
    await fetch(`/api/brain/rules/${id}`, { method: 'DELETE' })
    refetchRules()
    qc.invalidateQueries({ queryKey: ['brain-stats'] })
    showUndo(`已删除「${r ? r.rule.slice(0, 12) : '规则'}…」`, async () => {
      await fetch(`/api/brain/rules/${id}/restore`, { method: 'POST' })
    })
  }

  const validateRule = async (id: string, win: boolean) => {
    const r = rules.find(x => x.id === id)
    const prevConfidence = r ? r.confidence : 0.6   // 点击前快照，撤销时精确还原
    await fetch(`/api/brain/rules/${id}/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ win }),
    })
    refetchRules()
    showUndo(win ? '已标记为「有效」(+置信度)' : '已标记为「无效」(−置信度)', async () => {
      await fetch(`/api/brain/rules/${id}/revert-validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ win, prev_confidence: prevConfidence }),
      })
    })
  }

  // 点卡片右下角的「验证 N✓ M✗」计数，撤回一次（持久入口，不受 6 秒提示条限制）
  const unvalidateRule = async (id: string, win: boolean) => {
    await fetch(`/api/brain/rules/${id}/unvalidate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ win }),
    })
    refetchRules()
  }

  const TABS: { key: Tab; label: string }[] = [
    { key: 'feed',    label: '➕ 输入' },
    { key: 'rules',   label: `📋 规则库 ${stats.total_rules > 0 ? `(${stats.total_rules})` : ''}` },
    { key: 'playbook',label: '📖 交易系统' },
    { key: 'sources', label: `📁 历史 ${stats.total_sources > 0 ? `(${stats.total_sources})` : ''}` },
  ]

  return (
    <div className="min-h-screen bg-gray-950 text-white">

      {/* 撤销提示条（误点 有效/无效/删除 后 6 秒内可撤回） */}
      {undo && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3
                        bg-gray-800 border border-gray-600 rounded-xl shadow-2xl px-4 py-2.5
                        text-sm text-gray-200">
          <span>{undo.text}</span>
          <button
            onClick={doUndo}
            className="font-semibold text-blue-400 hover:text-blue-300 px-2 py-0.5 rounded-lg
                       border border-blue-700/50 hover:border-blue-500 transition-colors"
          >↩ 撤销</button>
          <button
            onClick={() => setUndo(null)}
            className="text-gray-500 hover:text-gray-300 transition-colors"
          >✕</button>
        </div>
      )}

      <div className="max-w-2xl mx-auto px-4 py-5 space-y-5">

        {/* 标题 */}
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-bold text-white">🧠 交易脑库</h1>
            {stats.total_rules > 0 && (
              <span className="text-xs text-blue-400 bg-blue-950/40 border border-blue-800/50 px-2 py-0.5 rounded-full">
                {stats.total_rules} 条规则
              </span>
            )}
          </div>
          <p className="text-xs text-gray-600">
            把你看到的好内容喂进来，AI 自动提炼成交易规则，慢慢进化成专属于你的交易系统
          </p>
        </div>

        {/* Tab 切换 */}
        <div className="flex gap-1 bg-gray-900 p-1 rounded-xl">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 text-xs py-2 rounded-lg font-medium transition-colors ${
                tab === t.key
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── 输入面板 ── */}
        {tab === 'feed' && (
          <div className="space-y-4">
            <AutoImportPanel onDone={() => {
              refetchRules()
              qc.invalidateQueries({ queryKey: ['brain-stats'] })
              qc.invalidateQueries({ queryKey: ['brain-sources'] })
            }} />
            <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-5">
              <FeedPanel onDone={() => {
                refetchRules()
                qc.invalidateQueries({ queryKey: ['brain-stats'] })
                qc.invalidateQueries({ queryKey: ['brain-sources'] })
                setTab('rules')
              }} />
            </div>
          </div>
        )}

        {/* ── 规则库 ── */}
        {tab === 'rules' && (
          <div className="space-y-4">
            {/* 分类筛选 */}
            <div className="flex gap-1.5 flex-wrap">
              <button
                onClick={() => setCatFilter('')}
                className={`text-xs px-3 py-1.5 rounded-xl border transition-colors ${
                  !catFilter ? 'bg-gray-700 border-gray-600 text-white' : 'bg-gray-900 border-gray-700 text-gray-500 hover:border-gray-600'
                }`}
              >
                全部 {stats.total_rules > 0 ? `(${stats.total_rules})` : ''}
              </button>
              {Object.entries(CATEGORIES).map(([key, cat]) => {
                const n = counts[key] ?? 0
                if (n === 0) return null
                return (
                  <button
                    key={key}
                    onClick={() => setCatFilter(catFilter === key ? '' : key)}
                    className={`text-xs px-3 py-1.5 rounded-xl border transition-colors ${
                      catFilter === key ? `${cat.bg} ${cat.color}` : 'bg-gray-900 border-gray-700 text-gray-500 hover:border-gray-600'
                    }`}
                  >
                    {cat.label} ({n})
                  </button>
                )
              })}
            </div>

            {rules.length === 0 ? (
              <div className="text-center py-12 space-y-3">
                <div className="text-4xl">🌱</div>
                <p className="text-gray-500 text-sm">脑库还是空的</p>
                <p className="text-gray-700 text-xs">去「输入」标签页喂入第一条内容吧</p>
                <button onClick={() => setTab('feed')} className="text-xs text-blue-400 border border-blue-800 px-4 py-2 rounded-xl hover:bg-blue-950/30 transition-colors">
                  去输入
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {rules.map(r => (
                  <RuleCard
                    key={r.id}
                    rule={r}
                    onDelete={deleteRule}
                    onValidate={validateRule}
                    onUnvalidate={unvalidateRule}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Playbook ── */}
        {tab === 'playbook' && <PlaybookPanel />}

        {/* ── 历史来源 ── */}
        {tab === 'sources' && (
          <SourcesPanel onDeleted={() => {
            refetchRules()
            qc.invalidateQueries({ queryKey: ['brain-stats'] })
          }} />
        )}

        {/* 底部提示 */}
        <div className="text-center text-[10px] text-gray-700 pb-4 space-y-0.5">
          <p>所有数据存储在本地 · 完全私密</p>
          <p>规则置信度会根据你的验证反馈自动调整</p>
        </div>
      </div>
    </div>
  )
}
