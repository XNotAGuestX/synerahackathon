const KEY = 'wayfinder-session-v1'

export type RecoveredSession = {
  id: string
  buildingId: string
  revision: number
  stepFree: boolean
  lastRouteId: string | null
  pendingActionId: string | null
}

export function readRecovery(buildingId: string): RecoveredSession | null {
  const raw = window.sessionStorage.getItem(KEY)
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as RecoveredSession
    return value.buildingId === buildingId && value.id ? value : null
  } catch {
    return null
  }
}

export function writeRecovery(value: RecoveredSession): void {
  window.sessionStorage.setItem(KEY, JSON.stringify(value))
}

export function clearRecovery(): void {
  window.sessionStorage.removeItem(KEY)
}
