import { useSyncExternalStore } from 'react'

export type AssistantPhase = 'premarket' | 'intraday' | 'postmarket' | string
export type AssistantTargetType = 'page' | 'market' | 'metric' | 'sector' | 'stock' | 'news'

export interface AssistantContext {
  page: string
  phase?: AssistantPhase
  target?: {
    type: AssistantTargetType
    name: string
    data?: Record<string, unknown>
  }
}

interface AssistantRequest {
  id: number
  context: AssistantContext
  suggestedQuestion?: string
}

interface AssistantState {
  isOpen: boolean
  request?: AssistantRequest
}

let state: AssistantState = { isOpen: false }
let requestId = 0
const listeners = new Set<() => void>()

function emit(next: AssistantState) {
  state = next
  listeners.forEach(listener => listener())
}

export const aiAssistantStore = {
  open(context: AssistantContext, suggestedQuestion?: string) {
    emit({
      isOpen: true,
      request: { id: ++requestId, context, suggestedQuestion },
    })
  },
  close() {
    emit({ ...state, isOpen: false })
  },
  getSnapshot() {
    return state
  },
  subscribe(listener: () => void) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
}

export function useAiAssistant() {
  return useSyncExternalStore(
    aiAssistantStore.subscribe,
    aiAssistantStore.getSnapshot,
    aiAssistantStore.getSnapshot,
  )
}

