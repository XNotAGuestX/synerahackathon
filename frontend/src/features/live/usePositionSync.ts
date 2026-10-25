import { useEffect, useRef } from 'react'
import { gateway } from '../../api/gateway'
import type { Point } from '../../domain/types'
import { shouldSend } from './shouldSend'
import type { SentSample } from './shouldSend'

export type Walker = { floorId: string; point: Point; jumpSeq: number }

// Samples the walker every 250 ms and PUTs throttled position fixes. getWalker returns null when nothing should be posted.
export function usePositionSync(sessionId: string, getWalker: () => Walker | null): void {
  const getRef = useRef(getWalker)
  getRef.current = getWalker
  useEffect(() => {
    if (!sessionId || sessionId.startsWith('local-')) return
    let sent: SentSample | null = null
    let inFlight = false
    const timer = window.setInterval(() => {
      const walker = getRef.current()
      if (!walker || inFlight) return
      const now = Date.now()
      const source = shouldSend(sent, walker, now)
      if (!source) return
      inFlight = true
      sent = { ...walker, at: now }
      gateway.putPosition(sessionId, { floor_id: walker.floorId, x_m: walker.point[0], y_m: walker.point[1], accuracy_m: null, measured_at: new Date(now).toISOString(), source })
        .catch(() => { sent = null })
        .finally(() => { inFlight = false })
    }, 250)
    return () => window.clearInterval(timer)
  }, [sessionId])
}
