/**
 * 自选股 store —— 模块级外部 store（跨页面共享、实时同步）
 *
 * 解决的痛点：
 *   1. 以前只有「我的自选」页能加自选；现在任何显示股票的地方都能放一个
 *      <WatchlistButton/>，点一下加/取消，所有页面立即同步（useSyncExternalStore）。
 *   2. 每只自选记下「加入日期」，「我的自选」页就能按日期分组（如「6.17 自选」），
 *      方便回看每天选的股后来表现如何。
 *
 * 持久化：localStorage。新格式 watchlist_v2 = WatchItem[]；
 * 首次加载时自动把旧的 watchlist_v1（纯 6 位代码数组）迁移过来（日期未知→归到「更早」）。
 */
import { useSyncExternalStore } from 'react'

export interface WatchItem {
  code: string          // 6 位代码
  name?: string         // 名称（加入时若已知则记下，否则由行情补全）
  date: string          // 加入日期 YYYY-MM-DD；'' 表示迁移来的旧数据（日期未知）
}

const LS_V2  = 'watchlist_v2'
const LS_V1  = 'watchlist_v1'   // 旧格式：JSON string[]

function todayStr(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function load(): WatchItem[] {
  // 优先读新格式
  try {
    const raw = localStorage.getItem(LS_V2)
    if (raw) {
      const arr = JSON.parse(raw)
      if (Array.isArray(arr)) {
        return arr
          .filter((x: unknown): x is WatchItem =>
            !!x && typeof (x as WatchItem).code === 'string')
          .map((x: WatchItem) => ({ code: x.code, name: x.name, date: x.date ?? '' }))
      }
    }
  } catch { /* ignore */ }

  // 迁移旧格式：纯代码数组 → 日期未知（''，归到「更早」）
  try {
    const rawV1 = localStorage.getItem(LS_V1)
    if (rawV1) {
      const codes = JSON.parse(rawV1)
      if (Array.isArray(codes)) {
        const migrated: WatchItem[] = codes
          .filter((c: unknown): c is string => typeof c === 'string' && /^\d{6}$/.test(c))
          .map((c: string) => ({ code: c, date: '' }))
        if (migrated.length) {
          localStorage.setItem(LS_V2, JSON.stringify(migrated))
          return migrated
        }
      }
    }
  } catch { /* ignore */ }

  return []
}

let items: WatchItem[] = load()
const listeners = new Set<() => void>()

function persist() {
  try { localStorage.setItem(LS_V2, JSON.stringify(items)) } catch { /* ignore */ }
}

function emit() {
  items = [...items]        // 新引用 → useSyncExternalStore 才感知变化
  persist()
  listeners.forEach(l => l())
}

export const watchlistStore = {
  /** 加自选（已存在则只补全名称，不改日期） */
  add(code: string, name?: string) {
    if (!/^\d{6}$/.test(code)) return
    const existing = items.find(i => i.code === code)
    if (existing) {
      if (name && !existing.name) { existing.name = name; emit() }
      return
    }
    items.push({ code, name, date: todayStr() })
    emit()
  },
  remove(code: string) {
    const next = items.filter(i => i.code !== code)
    if (next.length !== items.length) { items = next; emit() }
  },
  toggle(code: string, name?: string) {
    if (items.some(i => i.code === code)) this.remove(code)
    else this.add(code, name)
  },
  has(code: string): boolean {
    return items.some(i => i.code === code)
  },
  /** 仅在名称为空时补全（行情回来后调用） */
  fillName(code: string, name: string) {
    const it = items.find(i => i.code === code)
    if (it && !it.name && name) { it.name = name; emit() }
  },
  getAll(): WatchItem[] { return items },
  subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l) } },
}

/** 订阅整张自选列表 */
export function useWatchlist(): WatchItem[] {
  return useSyncExternalStore(watchlistStore.subscribe, watchlistStore.getAll, watchlistStore.getAll)
}

/** 订阅「某只股是否在自选里」（primitive 快照，安全） */
export function useInWatchlist(code: string): boolean {
  return useSyncExternalStore(
    watchlistStore.subscribe,
    () => watchlistStore.has(code),
    () => watchlistStore.has(code),
  )
}
