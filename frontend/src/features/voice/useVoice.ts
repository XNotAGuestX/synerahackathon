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
type Options = {
  active: boolean
  sessionId: string
  busy: boolean
  send: (text: string, signal: AbortSignal, onStart: () => void) => Promise<Reply | null>
}
const PRE_ROLL_FRAMES = 20 // 400 ms before speech detection
const FRAME_MS = 20

function concat(frames: Float32Array[]): Float32Array {
  const out = new Float32Array(frames.reduce((total, frame) => total + frame.length, 0))
  let at = 0
  for (const frame of frames) { out.set(frame, at); at += frame.length }
  return out
}

export function useVoice({ active, sessionId, busy, send }: Options) {
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
      const blob = await gateway.fetchSpeechClip(run.sessionId, item.clipId, abort.signal)
      if (!valid()) return
      const context = contextRef.current
      if (!context || context.state !== 'running') throw new Error(copy.voicePlaybackBlocked)
      const buffer = await context.decodeAudioData(await blob.arrayBuffer())
      if (!valid()) return
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
          if (reply.speechClipId && !utterancesRef.current.length && version === playbackVersion.current) {
            const drawn = reply.effects.findLast((effect) => effect.type === 'draw_route')
            const routeId = drawn?.type === 'draw_route' && typeof drawn.route_id === 'string' ? drawn.route_id : undefined
            if (routeId) queue.retainRoute(routeId)
            queue.enqueue({ kind: 'reply', clipId: reply.speechClipId, text: reply.speechText ?? '' })
          }
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
  }, [pump, queue, refresh])

  const speakGuidance = useCallback((event: GuidanceEvent) => {
    if (!activeRef.current || !event.speech_clip_id) return
    if (event.kind === 'stopped' || event.kind === 'arrived') stopPlayback()
    queue.enqueue({ kind: event.kind, clipId: event.speech_clip_id, text: event.text, routeId: event.route_id })
    void pump()
  }, [pump, queue, stopPlayback])

  // Each voice session owns its requests, recordings and audio context.
  useEffect(() => {
    if (!active) return
    const run: Run = { sessionId, controller: new AbortController(), draining: false }
    runRef.current = run
    setTranscript('')
    return () => {
      runRef.current.controller.abort()
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
  }, [active, sessionId, refresh, stopPlayback])

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
    return () => {
      cancelled = true
      finishRef.current = () => undefined
      capture.stop()
      utterance = null
      hearingRef.current = false
      setLevel(0)
      refresh()
    }
  }, [active, muted, ready, captureVersion, sessionId, drain, refresh, stopPlayback])

  useEffect(() => { if (!busy) void pump() }, [busy, pump])
  useEffect(() => {
    const pause = () => {
      if (!document.hidden || !activeRef.current) return
      runRef.current.controller.abort()
      runRef.current = { sessionId: sessionRef.current, controller: new AbortController(), draining: false }
      utterancesRef.current = []
      processingRef.current = null
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
  }, [refresh, stopPlayback])

  return { state, level, muted, setMuted, ready, error, transcript, queued, enable,
    finishSpeaking: () => finishRef.current(), speakGuidance,
    interruptPlayback: () => { stopPlayback(); refresh() } }
}
