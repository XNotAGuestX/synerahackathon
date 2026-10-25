import { useCallback, useEffect, useRef, useState } from 'react'
import { gateway } from '../../api/gateway'
import type { Guidance, GuidanceEvent } from '../../domain/types'

const MAX_EVENTS = 50
const WAIT_S = 20
const MAX_BACKOFF_MS = 10000

export type GuidanceFeedState = {
  guidance: Guidance | null
  events: GuidanceEvent[]
  latestInstruction: GuidanceEvent | null
  refresh: () => void
}

// Long-polls the guidance feed. onEvent fires once per new event, in order.
// While held, nothing is polled; events from that time arrive together on release.
export function useGuidanceFeed(sessionId: string, onEvent?: (event: GuidanceEvent) => void, held = false): GuidanceFeedState {
  const [guidance, setGuidance] = useState<Guidance | null>(null)
  const [events, setEvents] = useState<GuidanceEvent[]>([])
  const [nonce, setNonce] = useState(0)
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent
  const cursorRef = useRef(0)

  useEffect(() => {
    cursorRef.current = 0
    setGuidance(null)
    setEvents([])
  }, [sessionId])

  useEffect(() => {
    if (!sessionId || sessionId.startsWith('local-') || held) return
    const abort = new AbortController()
    let failures = 0
    const run = async () => {
      let first = true
      while (!abort.signal.aborted) {
        try {
          const feed = await gateway.getGuidance(sessionId, cursorRef.current, first ? 0 : WAIT_S, abort.signal)
          first = false
          failures = 0
          if (abort.signal.aborted) return
          const fresh = feed.events.filter((event) => event.seq > cursorRef.current)
          cursorRef.current = Math.max(cursorRef.current, feed.cursor, ...fresh.map((event) => event.seq))
          setGuidance(feed.guidance)
          if (fresh.length) {
            setEvents((current) => [...current, ...fresh].slice(-MAX_EVENTS))
            for (const event of fresh) onEventRef.current?.(event)
          }
        } catch {
          if (abort.signal.aborted) return
          failures += 1
          await new Promise((resolve) => window.setTimeout(resolve, Math.min(MAX_BACKOFF_MS, 500 * 2 ** failures)))
        }
      }
    }
    void run()
    return () => abort.abort()
  }, [sessionId, nonce, held])

  const refresh = useCallback(() => setNonce((value) => value + 1), [])
  return { guidance, events, latestInstruction: events.at(-1) ?? null, refresh }
}
