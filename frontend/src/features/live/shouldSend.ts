export type SyncSample = { floorId: string; point: [number, number]; jumpSeq: number }
export type SentSample = SyncSample & { at: number }

export const MIN_MOVE_M = 0.3
export const MIN_GAP_MS = 1000
export const HEARTBEAT_MS = 5000

// Decides whether the sampled walker position should be PUT now, and with which source.
export function shouldSend(prev: SentSample | null, next: SyncSample, now: number): 'manual' | 'simulated' | null {
  if (!prev) return next.jumpSeq > 0 ? 'manual' : 'simulated'
  if (next.jumpSeq !== prev.jumpSeq || next.floorId !== prev.floorId) return 'manual'
  const elapsed = now - prev.at
  const moved = Math.hypot(next.point[0] - prev.point[0], next.point[1] - prev.point[1])
  if (moved >= MIN_MOVE_M && elapsed >= MIN_GAP_MS) return 'simulated'
  if (elapsed >= HEARTBEAT_MS) return 'simulated'
  return null
}
