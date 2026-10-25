import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/errors'
import { gateway } from '../../api/gateway'
import type { GuidanceEvent, Reply } from '../../domain/types'
import { copy } from '../../i18n/en'
import { createCapture, microphoneMessage, SAMPLE_RATE } from './capture'
import { createSpeechQueue } from './speech-queue'
import type { SpeechItem } from './speech-queue'
import { createVad, frameRms } from './vad'
import { encodeWav } from './wav'

export type VoiceState = 'off' | 'listening' | 'hearing' | 'transcribing' | 'queued' | 'thinking' | 'speaking'
type Run = { sessionId: string; controller: AbortController; draining: boolean }
type Prefetched = { reply: Promise<Reply>; commit: () => Promise<Reply | null>; release: () => void }
type Options = {
  active: boolean
  sessionId: string
  busy: boolean
  send: (text: string, signal: AbortSignal, onStart: () => void) => Promise<Reply | null>
  prefetch?: (text: string) => Prefetched | null
}
const PRE_ROLL_FRAMES = 20 // 400 ms before speech detection
const FRAME_MS = 20

// Voice delay mock, switched on only by the server's undocumented --voice-delay-mock flag. It is just for speed
// in the demo video, never for real use: whatever the user says, the turn is MOCK_QUESTION. It is sent (without
// speech-to-text) as soon as the microphone opens, its spoken answer is fetched and decoded while the user talks,
// and Mute reveals it, with chat, map and guidance as usual, exactly MOCK_DELAY_MS after the press.
const MOCK_QUESTION = 'Guide me to the nearest toilet from my position.'
const MOCK_DELAY_MS = 500
type Speculation = Prefetched & { run: Run; clip: Promise<{ clipId: string; buffer: AudioBuffer } | null> }

function concat(frames: Float32Array[]): Float32Array {
  const out = new Float32Array(frames.reduce((total, frame) => total + frame.length, 0))
  let at = 0
  for (const frame of frames) { out.set(frame, at); at += frame.length }
  return out
}

export function useVoice({ active, sessionId, busy, send, prefetch }: Options) {
  const [state, setState] = useState<VoiceState>('off')
  const [level, setLevel] = useState(0)
  const [muted, setMuted] = useState(false)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [transcript, setTranscript] = useState('')
  const [queued, setQueued] = useState(0)
  const [captureVersion, setCaptureVersion] = useState(0)
  const sendRef = useRef(send)
  sendRef.current = send
  const prefetchRef = useRef(prefetch)
  prefetchRef.current = prefetch
  const [mock, setMock] = useState(false)
  const speculationRef = useRef<Speculation | null>(null)
  const decodedRef = useRef(new Map<string, AudioBuffer>())
  const sessionRef = useRef(sessionId)
  sessionRef.current = sessionId
  const activeRef = useRef(active)
  activeRef.current = active
  const busyRef = useRef(busy)
  busyRef.current = busy
  const readyRef = useRef(false)
  const contextRef = useRef<AudioContext | null>(null)
  const sourceRef = useRef<AudioBufferSourceNode | null>(null)
  const playbackAbort = useRef<AbortController | null>(null)
  const playbackVersion = useRef(0)
  const playingRef = useRef(false)
  const hearingRef = useRef(false)
  const processingRef = useRef<VoiceState | null>(null)
  const utterancesRef = useRef<Blob[]>([])
  const finishRef = useRef<() => void>(() => undefined)
  const blockedClip = useRef<SpeechItem | null>(null)
  const runRef = useRef<Run>({ sessionId, controller: new AbortController(), draining: false })
  const queue = useRef(createSpeechQueue()).current

  const current = (run: Run) => runRef.current === run && !run.controller.signal.aborted
    && activeRef.current && run.sessionId === sessionRef.current

  const refresh = useCallback(() => {
    if (!activeRef.current || !readyRef.current) setState('off')
    else if (hearingRef.current) setState('hearing')
    else if (processingRef.current) setState(processingRef.current)
    else setState(playingRef.current ? 'speaking' : 'listening')
  }, [])

  const stopPlayback = useCallback(() => {
    playbackVersion.current += 1
    playbackAbort.current?.abort()
    if (sourceRef.current) {
      sourceRef.current.onended = null
      sourceRef.current.stop()
      sourceRef.current.disconnect()
      sourceRef.current = null
    }
    queue.interrupt()
    blockedClip.current = null
    playingRef.current = false
  }, [queue])

  const pump = useCallback(async () => {
    if (!activeRef.current || !readyRef.current || playingRef.current || hearingRef.current
      || processingRef.current || busyRef.current || blockedClip.current || document.hidden) return
    const item = queue.next()
    if (!item) { refresh(); return }
    const run = runRef.current
    const version = playbackVersion.current
    const abort = new AbortController()
    playbackAbort.current = abort
    playingRef.current = true
    refresh()
    const valid = () => current(run) && version === playbackVersion.current
    try {
      let buffer = decodedRef.current.get(item.clipId)
      decodedRef.current.delete(item.clipId)
      const context = contextRef.current
      if (!buffer) {
        const blob = await gateway.fetchSpeechClip(run.sessionId, item.clipId, abort.signal)
        if (!valid()) return
        if (!context || context.state !== 'running') throw new Error(copy.voicePlaybackBlocked)
        buffer = await context.decodeAudioData(await blob.arrayBuffer())
        if (!valid()) return
      } else if (!context || context.state !== 'running') throw new Error(copy.voicePlaybackBlocked)
      const source = context.createBufferSource()
      source.buffer = buffer
      source.connect(context.destination)
      sourceRef.current = source
      source.onended = () => {
        source.disconnect()
        if (!valid()) return
        sourceRef.current = null
        playingRef.current = false
        refresh()
        void pump()
      }
      source.start()
    } catch (failure) {
      if (!valid() || abort.signal.aborted) return
      blockedClip.current = item
      playingRef.current = false
      setError(failure instanceof Error && failure.message === copy.voicePlaybackBlocked
        ? copy.voicePlaybackBlocked : copy.voicePlaybackFailed)
      refresh()
    }
  }, [queue, refresh])

  // Called directly by a click/tap, before asynchronous microphone/network work.
  const enable = useCallback(() => {
    try {
      if (!window.isSecureContext) throw new Error(copy.speechSecureContext)
      const context = contextRef.current ?? new AudioContext()
      contextRef.current = context
      const resumed = context.resume()
      resumed.then(() => {
        if (contextRef.current !== context) return
        readyRef.current = true
        setReady(true)
        setMuted(false)
        setError(null)
        setCaptureVersion((version) => version + 1)
        if (blockedClip.current) { queue.enqueue(blockedClip.current); blockedClip.current = null }
        refresh()
        void pump()
      }).catch(() => setError(copy.voicePlaybackBlocked))
    } catch (failure) { setError(failure instanceof Error ? failure.message : copy.speechPermissionFailed) }
  }, [pump, queue, refresh])

  const speakReply = useCallback((reply: Reply) => {
    if (!reply.speechClipId) return
    const drawn = reply.effects.findLast((effect) => effect.type === 'draw_route')
    const routeId = drawn?.type === 'draw_route' && typeof drawn.route_id === 'string' ? drawn.route_id : undefined
    if (routeId) queue.retainRoute(routeId)
    queue.enqueue({ kind: 'reply', clipId: reply.speechClipId, text: reply.speechText ?? '' })
  }, [queue])

  // Voice delay mock: Mute shows the prefetched turn as if the user's words had just been understood.
  const reveal = useCallback((pressed: number) => {
    const speculation = speculationRef.current
    if (!speculation) return
    speculationRef.current = null
    const { run } = speculation
    processingRef.current = 'thinking'
    refresh()
    void (async () => {
      try {
        const clip = await speculation.clip
        await new Promise((resolve) => window.setTimeout(resolve, MOCK_DELAY_MS - (performance.now() - pressed)))
        if (!current(run)) return
        if (clip) decodedRef.current.set(clip.clipId, clip.buffer)
        setTranscript(MOCK_QUESTION)
        const reply = await speculation.commit()
        if (!current(run)) return
        if (!reply) { setError(copy.voiceRequestFailed); return }
        setError(null)
        speakReply(reply)
      } finally {
        speculation.release()
        if (current(run)) { processingRef.current = null; refresh(); void pump() }
      }
    })()
  }, [pump, refresh, speakReply])

  const drain = useCallback(async () => {
    const run = runRef.current
    if (run.draining) return
    run.draining = true
    try {
      while (utterancesRef.current.length && current(run)) {
        const wav = utterancesRef.current.shift()!
        const version = playbackVersion.current
        setQueued(utterancesRef.current.length)
        processingRef.current = 'transcribing'
        refresh()
        try {
          const text = (await gateway.transcribe(run.sessionId, wav, run.controller.signal)).text.trim()
          if (!current(run)) return
          if (!text) { setError(copy.voiceNotHeard); continue }
          setTranscript(text)
          setError(null)
          processingRef.current = 'queued'
          refresh()
          const reply = await sendRef.current(text, run.controller.signal, () => {
            if (current(run)) { processingRef.current = 'thinking'; refresh() }
          })
          if (!current(run)) return
          if (!reply) { setError(copy.voiceRequestFailed); continue }
          // A newer utterance interrupts this reply, but its written answer remains visible.
          if (!utterancesRef.current.length && version === playbackVersion.current) speakReply(reply)
        } catch (failure) {
          if (!current(run)) return
          setError(failure instanceof ApiError && failure.code === '40004_speech_unavailable'
            ? copy.voiceUnavailable : failure instanceof Error ? failure.message : copy.voiceUnavailable)
        }
      }
    } finally {
      run.draining = false
      if (current(run)) { processingRef.current = null; refresh(); void pump() }
    }
  }, [pump, refresh, speakReply])

  const speakGuidance = useCallback((event: GuidanceEvent) => {
    if (!activeRef.current || !event.speech_clip_id) return
    if (event.kind === 'stopped' || event.kind === 'arrived') stopPlayback()
    queue.enqueue({ kind: event.kind, clipId: event.speech_clip_id, text: event.text, routeId: event.route_id })
    void pump()
  }, [pump, queue, stopPlayback])

  // Voice delay mock: an unshown turn stays on the server; only its guidance is no longer held back.
  const dropSpeculation = useCallback(() => {
    speculationRef.current?.release()
    speculationRef.current = null
    decodedRef.current.clear()
  }, [])

  useEffect(() => {
    let cancelled = false
    void gateway.voiceDelayMock().then((on) => { if (!cancelled) setMock(on) })
    return () => { cancelled = true }
  }, [])

  // Each voice session owns its requests, recordings and audio context.
  useEffect(() => {
    if (!active) return
    const run: Run = { sessionId, controller: new AbortController(), draining: false }
    runRef.current = run
    setTranscript('')
    return () => {
      runRef.current.controller.abort()
      dropSpeculation()
      stopPlayback()
      utterancesRef.current = []
      processingRef.current = null
      hearingRef.current = false
      readyRef.current = false
      setReady(false)
      setQueued(0)
      setTranscript('')
      setLevel(0)
      const context = contextRef.current
      contextRef.current = null
      void context?.close().catch(() => undefined)
      refresh()
    }
  }, [active, sessionId, dropSpeculation, refresh, stopPlayback])

  useEffect(() => {
    const context = contextRef.current
    if (!active || muted || !ready || !context || !sessionId) return
    const run = runRef.current
    const vad = createVad()
    const ring: Float32Array[] = []
    let utterance: Float32Array[] | null = null
    let frames = 0
    const finish = () => {
      if (!utterance || !current(run)) return
      const audio = concat(utterance)
      utterance = null // manual completion and VAD completion cannot submit twice
      ring.length = 0
      vad.reset()
      hearingRef.current = false
      if (mock) { refresh(); return } // the voice delay mock answers on Mute, not on what was heard
      utterancesRef.current.push(new Blob([encodeWav(audio, SAMPLE_RATE)], { type: 'audio/wav' }))
      setQueued(utterancesRef.current.length)
      refresh()
      void drain()
    }
    finishRef.current = finish
    const capture = createCapture(context, (frame) => {
      if (!current(run)) return
      const rms = frameRms(frame)
      if (++frames % 3 === 0) setLevel(Math.min(1, rms * 8))
      const event = vad.push(rms, FRAME_MS, playingRef.current)
      if (event === 'start') {
        stopPlayback()
        utterance = [...ring]
        hearingRef.current = true
        refresh()
      }
      if (utterance) utterance.push(frame)
      else { ring.push(frame); if (ring.length > PRE_ROLL_FRAMES) ring.shift() }
      if (event === 'end') finish()
    })
    let cancelled = false
    capture.start().catch((failure: unknown) => {
      capture.stop()
      if (!cancelled && current(run)) { setError(microphoneMessage(failure)); setMuted(true) }
    })
    // Voice delay mock: the open microphone starts the canned turn, so its answer is ready before Mute.
    const prefetched = mock && !speculationRef.current ? prefetchRef.current?.(MOCK_QUESTION) : null
    if (prefetched) {
      const clip = prefetched.reply.then(async (reply) => {
        if (!reply.speechClipId) return null
        const blob = await gateway.fetchSpeechClip(run.sessionId, reply.speechClipId, run.controller.signal)
        return { clipId: reply.speechClipId, buffer: await context.decodeAudioData(await blob.arrayBuffer()) }
      }).catch(() => null)
      speculationRef.current = { ...prefetched, run, clip }
    }
    return () => {
      cancelled = true
      finishRef.current = () => undefined
      capture.stop()
      utterance = null
      hearingRef.current = false
      setLevel(0)
      refresh()
    }
  }, [active, muted, ready, captureVersion, sessionId, mock, drain, refresh, stopPlayback])

  useEffect(() => { if (!busy) void pump() }, [busy, pump])
  useEffect(() => {
    const pause = () => {
      if (!document.hidden || !activeRef.current) return
      runRef.current.controller.abort()
      runRef.current = { sessionId: sessionRef.current, controller: new AbortController(), draining: false }
      utterancesRef.current = []
      processingRef.current = null
      dropSpeculation()
      stopPlayback()
      readyRef.current = false
      setReady(false)
      setQueued(0)
      setError(copy.voiceResumeHint)
      void contextRef.current?.suspend()
      refresh()
    }
    document.addEventListener('visibilitychange', pause)
    return () => document.removeEventListener('visibilitychange', pause)
  }, [dropSpeculation, refresh, stopPlayback])

  return { state, level, muted, ready, error, transcript, queued, enable,
    setMuted: (next: boolean) => { if (next) reveal(performance.now()); setMuted(next) },
    finishSpeaking: () => finishRef.current(), speakGuidance,
    interruptPlayback: () => { stopPlayback(); refresh() } }
}
