/**
 * 顶级导航 —— 拖动跟手排序 + 横向滑动
 * - 鼠标：按住标签直接拖，标签实时跟随鼠标，其它标签平滑让位
 * - 触摸：长按（~250ms）激活后跟手拖动（避免与页面横向滑动冲突）
 * - 顺序持久化到 localStorage，下次进入沿用
 * - 标签过多时容器可横向滑动
 * - 普通点击 = 切换标签
 */
import { useState, useRef, useEffect, useCallback } from 'react'

export interface NavTab {
  key: string
  label: string
  icon: string
  desc?: string
}

const GAP_PX = 8           // 标签间距（与 gap-2 对应）
const LONG_PRESS_MS = 250  // 触摸长按激活拖动
const MOUSE_DRAG_PX = 5    // 鼠标移动超过此距离即进入拖动
const CLICK_SLOP_PX = 5    // 抬起时移动小于此距离视作点击

interface Rect { left: number; width: number; center: number }
interface DragState { key: string; dx: number; over: number }

export default function DraggableNav({
  tabs,
  activeKey,
  onSelect,
  storageKey = 'main_nav_order_v1',
}: {
  tabs: NavTab[]
  activeKey: string
  onSelect: (key: string) => void
  storageKey?: string
}) {
  const tabMap: Record<string, NavTab> = Object.fromEntries(tabs.map(t => [t.key, t]))
  const allKeys = tabs.map(t => t.key)
  const allKeysSig = allKeys.join(',')

  // ── 顺序状态（持久化）──────────────────────────────────────────────
  const [order, setOrder] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      if (raw) {
        const saved: string[] = JSON.parse(raw)
        const known = saved.filter(k => allKeys.includes(k))
        const missing = allKeys.filter(k => !known.includes(k))
        return [...known, ...missing]
      }
    } catch { /* ignore */ }
    return allKeys
  })

  useEffect(() => {
    setOrder(prev => {
      const known = prev.filter(k => allKeys.includes(k))
      const missing = allKeys.filter(k => !known.includes(k))
      const next = [...known, ...missing]
      const same = next.length === prev.length && next.every((k, i) => k === prev[i])
      return same ? prev : next
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allKeysSig])

  const orderRef = useRef(order)
  useEffect(() => { orderRef.current = order }, [order])

  const persist = useCallback((next: string[]) => {
    try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch { /* ignore */ }
  }, [storageKey])

  // ── 拖动交互 ────────────────────────────────────────────────────────
  const [drag, setDrag] = useState<DragState | null>(null)
  const btnRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  const pressTimer = useRef<number | null>(null)
  const pointerId = useRef<number>(-1)
  const startX = useRef(0)
  const activeKeyRef = useRef<string | null>(null)   // 正在按住/拖动的 key
  const draggingRef = useRef(false)
  const rectsRef = useRef<Record<string, Rect>>({})  // 拖动开始时的布局快照
  const baseOrderRef = useRef<string[]>([])           // 拖动开始时的顺序
  const fromIndexRef = useRef(0)
  const slotRef = useRef(0)                            // 被拖标签占位宽度(+gap)
  const dragCenter0Ref = useRef(0)                     // 被拖标签初始中心 X

  const clearTimer = () => {
    if (pressTimer.current != null) { clearTimeout(pressTimer.current); pressTimer.current = null }
  }

  // 快照当前布局，进入拖动
  const beginDrag = (key: string) => {
    const rects: Record<string, Rect> = {}
    for (const k of orderRef.current) {
      const el = btnRefs.current[k]
      if (!el) continue
      const r = el.getBoundingClientRect()
      rects[k] = { left: r.left, width: r.width, center: r.left + r.width / 2 }
    }
    rectsRef.current = rects
    baseOrderRef.current = [...orderRef.current]
    fromIndexRef.current = orderRef.current.indexOf(key)
    slotRef.current = (rects[key]?.width ?? 0) + GAP_PX
    dragCenter0Ref.current = rects[key]?.center ?? 0
    draggingRef.current = true
    const el = btnRefs.current[key]
    try { el?.setPointerCapture(pointerId.current) } catch { /* ignore */ }
    setDrag({ key, dx: 0, over: fromIndexRef.current })
  }

  // 根据指针 X 求落点 index
  const computeOver = (pointerCenter: number, key: string): number => {
    let over = 0
    for (const k of baseOrderRef.current) {
      if (k === key) continue
      if (rectsRef.current[k]?.center < pointerCenter) over++
    }
    return over
  }

  const onPointerDown = (e: React.PointerEvent<HTMLButtonElement>, key: string) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    startX.current = e.clientX
    pointerId.current = e.pointerId
    activeKeyRef.current = key
    draggingRef.current = false
    clearTimer()
    if (e.pointerType !== 'mouse') {
      // 触摸/笔：长按激活
      pressTimer.current = window.setTimeout(() => beginDrag(key), LONG_PRESS_MS)
    }
  }

  const onPointerMove = (e: React.PointerEvent<HTMLButtonElement>, key: string) => {
    if (activeKeyRef.current !== key) return
    if (!draggingRef.current) {
      const moved = Math.abs(e.clientX - startX.current)
      if (e.pointerType === 'mouse') {
        if (moved > MOUSE_DRAG_PX) beginDrag(key)   // 鼠标：动起来就进入拖动
        else return
      } else {
        if (moved > MOUSE_DRAG_PX) clearTimer()      // 触摸：长按前就滑动 → 取消(让页面滚动)
        return
      }
    }
    e.preventDefault()
    const dx = e.clientX - startX.current
    const over = computeOver(dragCenter0Ref.current + dx, key)
    setDrag(prev => (prev && prev.dx === dx && prev.over === over ? prev : { key, dx, over }))
  }

  const endDrag = (e: React.PointerEvent<HTMLButtonElement>, key: string) => {
    if (activeKeyRef.current !== key) return
    clearTimer()
    try { btnRefs.current[key]?.releasePointerCapture(pointerId.current) } catch { /* ignore */ }
    if (draggingRef.current) {
      const from = fromIndexRef.current
      const over = computeOver(dragCenter0Ref.current + (e.clientX - startX.current), key)
      const next = [...baseOrderRef.current]
      next.splice(from, 1)
      next.splice(over, 0, key)
      draggingRef.current = false
      activeKeyRef.current = null
      setDrag(null)
      const changed = next.some((k, i) => k !== baseOrderRef.current[i])
      if (changed) { setOrder(next); persist(next) }
    } else {
      activeKeyRef.current = null
      if (Math.abs(e.clientX - startX.current) < CLICK_SLOP_PX) onSelect(key)
    }
  }

  const cancelDrag = () => {
    clearTimer()
    activeKeyRef.current = null
    if (draggingRef.current) {
      draggingRef.current = false
      setDrag(null)
    }
  }

  // 计算每个标签的位移
  const transformFor = (key: string): { tx: number; dragging: boolean } => {
    if (!drag) return { tx: 0, dragging: false }
    if (key === drag.key) return { tx: drag.dx, dragging: true }
    const from = fromIndexRef.current
    const over = drag.over
    const idx = baseOrderRef.current.indexOf(key)
    const slot = slotRef.current
    if (over > from && idx > from && idx <= over) return { tx: -slot, dragging: false }
    if (over < from && idx >= over && idx < from) return { tx: slot, dragging: false }
    return { tx: 0, dragging: false }
  }

  return (
    <div
      className="flex items-center gap-2 overflow-x-auto min-w-0 nav-scroll"
      style={{ scrollbarWidth: 'none' }}
    >
      {order.map(key => {
        const t = tabMap[key]
        if (!t) return null
        const active = activeKey === key
        const { tx, dragging } = transformFor(key)
        return (
          <button
            key={key}
            ref={el => { btnRefs.current[key] = el }}
            onPointerDown={e => onPointerDown(e, key)}
            onPointerMove={e => onPointerMove(e, key)}
            onPointerUp={e => endDrag(e, key)}
            onPointerCancel={cancelDrag}
            title={t.desc}
            style={{
              transform: tx ? `translateX(${tx}px)` : undefined,
              transition: dragging ? 'none' : 'transform 200ms ease',
              zIndex: dragging ? 50 : undefined,
              position: 'relative',
            }}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium whitespace-nowrap select-none touch-none ${
              active
                ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/30'
                : 'text-gray-400 hover:text-white hover:bg-gray-800'
            } ${
              dragging
                ? 'scale-105 shadow-2xl shadow-black/50 ring-2 ring-blue-400/70 cursor-grabbing'
                : 'cursor-grab'
            }`}
          >
            <span className="text-base pointer-events-none">{t.icon}</span>
            <span className="pointer-events-none">{t.label}</span>
          </button>
        )
      })}
    </div>
  )
}
