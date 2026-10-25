import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/errors'
import { gateway } from '../../api/gateway'
import type { EmergencyRoster, EmergencyStatus } from '../../api/gateway'

const STATUS_POLL_MS = 3000
const ROSTER_POLL_MS = 2000
const TOKEN_KEY = 'wayfinder-admin-token'

/** Runs `task` now and every `intervalMs` while enabled; skips hidden tabs and never overlaps calls. */
function usePolling(task: (valid: () => boolean) => Promise<void>, intervalMs: number, enabled: boolean, key: string): void {
  const taskRef = useRef(task)
  taskRef.current = task
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let running = false
    const valid = () => !cancelled
    const run = async () => {
      if (cancelled || running || document.hidden) return
      running = true
      try { await taskRef.current(valid) } finally { running = false }
    }
    const timer = window.setInterval(() => { void run() }, intervalMs)
    document.addEventListener('visibilitychange', run)
    void run()
    return () => { cancelled = true; window.clearInterval(timer); document.removeEventListener('visibilitychange', run) }
  }, [enabled, intervalMs, key])
}

/** Public alarm state of the building, for the banner on every phone. Errors keep the last known state. */
export function useEmergencyStatus(buildingId: string): [EmergencyStatus | null, (status: EmergencyStatus) => void] {
  const [status, setStatus] = useState<EmergencyStatus | null>(null)
  useEffect(() => setStatus(null), [buildingId])
  const enabled = Boolean(buildingId) && !buildingId.startsWith('imported:')
  usePolling(async (valid) => {
    try {
      const next = await gateway.getEmergency(buildingId)
      if (valid()) setStatus(next)
    } catch { /* a missed poll is retried on the next tick */ }
  }, STATUS_POLL_MS, enabled, buildingId)
  return [status, setStatus]
}

export type AdminSession = { token: string; name: string }

/** Admin token for this tab only (sessionStorage); the PIN itself is never stored. */
export function useAdminToken(): [AdminSession | null, (session: AdminSession | null) => void] {
  const [session, setSession] = useState<AdminSession | null>(() => {
    try { return JSON.parse(window.sessionStorage.getItem(TOKEN_KEY) ?? 'null') as AdminSession | null } catch { return null }
  })
  const update = useCallback((next: AdminSession | null) => {
    if (next) window.sessionStorage.setItem(TOKEN_KEY, JSON.stringify(next))
    else window.sessionStorage.removeItem(TOKEN_KEY)
    setSession(next)
  }, [])
  return [session, update]
}

/** Live list for the admin while the alarm is active. A rejected token locks the admin view again. */
export function useEmergencyRoster(buildingId: string, token: string | null, active: boolean, onTokenRejected: () => void) {
  const [roster, setRoster] = useState<EmergencyRoster | null>(null)
  const [failed, setFailed] = useState(false)
  const rejectedRef = useRef(onTokenRejected)
  rejectedRef.current = onTokenRejected
  useEffect(() => { if (!active) setRoster(null) }, [active, buildingId])
  usePolling(async (valid) => {
    if (!token) return
    try {
      const next = await gateway.listEmergencyPeople(buildingId, token)
      if (!valid()) return
      setRoster(next.active ? next : null)
      setFailed(false)
    } catch (error: unknown) {
      if (!valid()) return
      if (error instanceof ApiError && (error.code === '10002_forbidden' || error.code === '10003_admin_disabled')) rejectedRef.current()
      else setFailed(true)
    }
  }, ROSTER_POLL_MS, Boolean(token) && active, `${buildingId}|${token}`)
  return { roster, setRoster, failed }
}
