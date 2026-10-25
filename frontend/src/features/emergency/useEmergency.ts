import { useCallback, useEffect, useRef, useState } from 'react'
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

export type EmergencyState = {
  status: EmergencyStatus | null
  roster: EmergencyRoster | null
  setRoster: (roster: EmergencyRoster | null) => void
  failed: boolean
}

/** Alarm state for every phone. Without an alarm only the light status is polled; during one, the public list
 *  (ADR-0004), which also tells when the alarm ends. Errors keep the last known state and retry on the next tick. */
export function useEmergency(buildingId: string): EmergencyState {
  const [roster, setRosterState] = useState<EmergencyRoster | null>(null)
  const [inactive, setInactive] = useState<EmergencyStatus | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => { setRosterState(null); setInactive(null); setFailed(false) }, [buildingId])
  const setRoster = useCallback((next: EmergencyRoster | null) => {
    setRosterState(next?.active ? next : null)
    if (!next?.active) setInactive({ building_id: buildingId, active: false, reason: null, started_at: null })
  }, [buildingId])
  const enabled = Boolean(buildingId) && !buildingId.startsWith('imported:')
  const active = Boolean(roster)
  usePolling(async (valid) => {
    try {
      if (active) {
        const next = await gateway.listEmergencyPeople(buildingId)
        if (valid()) setRoster(next)
      } else {
        const status = await gateway.getEmergency(buildingId)
        if (!valid()) return
        if (status.active) setRoster(await gateway.listEmergencyPeople(buildingId))
        else setInactive(status)
      }
      if (valid()) setFailed(false)
    } catch {
      if (valid()) setFailed(true)
    }
  }, active ? ROSTER_POLL_MS : STATUS_POLL_MS, enabled, `${buildingId}|${active}`)
  const status: EmergencyStatus | null = roster
    ? { building_id: roster.building_id, active: true, reason: roster.reason, started_at: roster.started_at }
    : inactive
  return { status, roster, setRoster, failed }
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

