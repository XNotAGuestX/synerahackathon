export type VadEvent = 'start' | 'end' | null
export type VadOptions = {
  minimum?: number
  startMs?: number
  startMsPlayback?: number
  endMs?: number
  maxMs?: number
  floorAlpha?: number
}

// Energy VAD. While playback is active the start threshold doubles and the hold time
// grows, so the speaker's own echo is unlikely to trigger barge-in.
export function createVad(options: VadOptions = {}) {
  const { minimum = 0.015, startMs = 250, startMsPlayback = 400, endMs = 800, maxMs = 15000, floorAlpha = 0.02 } = options
  let floor = 0.005
  let speaking = false
  let loudMs = 0
  let quietMs = 0
  let speechMs = 0
  return {
    push(rms: number, frameMs: number, playbackActive: boolean): VadEvent {
      const base = Math.max(floor * 3, minimum)
      if (!speaking) {
        const threshold = playbackActive ? base * 2 : base
        if (rms > threshold) loudMs += frameMs
        else {
          loudMs = 0
          floor += (rms - floor) * floorAlpha
        }
        if (loudMs >= (playbackActive ? startMsPlayback : startMs)) {
          speaking = true
          loudMs = 0
          quietMs = 0
          speechMs = 0
          return 'start'
        }
        return null
      }
      speechMs += frameMs
      quietMs = rms > base ? 0 : quietMs + frameMs
      if (quietMs >= endMs || speechMs >= maxMs) {
        speaking = false
        quietMs = 0
        return 'end'
      }
      return null
    },
    reset() { speaking = false; loudMs = 0; quietMs = 0; speechMs = 0 },
  }
}

export function frameRms(frame: Float32Array): number {
  let sum = 0
  for (let i = 0; i < frame.length; i += 1) sum += frame[i] * frame[i]
  return frame.length ? Math.sqrt(sum / frame.length) : 0
}
