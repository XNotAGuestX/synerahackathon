import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/errors'
import { gateway } from '../../api/gateway'
import type { GuidanceEvent, Reply } from '../../domain/types'
import { copy } from '../../i18n/en'
import type { TranscriptionToken } from '../../api/gateway'
import { createCapture, microphoneMessage, SAMPLE_RATE } from './capture'
import { openTranscriptStream } from './realtime'
import type { TranscriptStream } from './realtime'
import { createSpeechQueue } from './speech-queue'
import type { SpeechItem } from './speech-queue'
import { createVad, frameRms } from './vad'
import { encodeWav } from './wav'

export type VoiceState = 'off' | 'listening' | 'hearing' | 'transcribing' | 'thinking' | 'speaking'

const PRE_ROLL_FRAMES = 20 // 400 ms of 20 ms frames
const FRAME_MS = 20
const TOKEN_MAX_AGE_MS = 10 * 60 * 1000 // provider tokens expire after 15 minutes

// text is the streamed transcript, committed as soon as the user stops talking.
type Utterance = { wav: Blob; text: Promise<string> | null }

type Options = {
  active: boolean
  sessionId: string
  // Sends one voice message and resolves with the reply, or null when it failed or was skipped.
  send: (text: string) => Promise<Reply | null>
}

function concat(frames: Float32Array[]): Float32Array {
  const out = new Float32Array(frames.reduce((total, frame) => total + frame.length, 0))
  let at = 0
  for (const frame of frames) { out.set(frame, at); at += frame.length }
  return out
}

export function useVoice({ active, sessionId, send }: Options) {
  const [state, setState] = useState<VoiceState>('off')
  const [level, setLevel] = useState(0)
  const [muted, setMuted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sendRef = useRef(send)
  sendRef.current = send
  const sessionRef = useRef(sessionId)
  sessionRef.current = sessionId
  const activeRef = useRef(active)
  activeRef.current = active

  const queue = useRef(createSpeechQueue()).current
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const urlRef = useRef<string | null>(null)
  const playingRef = useRef(false)
  const generationRef = useRef(0)
  const hearingRef = useRef(false)
  const processingRef = useRef<'transcribing' | 'thinking' | null>(null)
  const utterancesRef = useRef<Utterance[]>([])
  const streamRef = useRef<TranscriptStream | null>(null)
  const tokenRef = useRef<{ sessionId: string; at: number; token: Promise<TranscriptionToken> } | null>(null)

  // One token is fetched ahead, so a new utterance can start streaming at once.
  const prefetchToken = useCallback(() => {
    const token = gateway.createTranscriptionToken(sessionRef.current)
    token.catch(() => undefined)
    tokenRef.current = { sessionId: sessionRef.current, at: Date.now(), token }
  }, [])
  const takeToken = useCallback((): Promise<TranscriptionToken> => {
    const cached = tokenRef.current
    const fresh = cached && cached.sessionId === sessionRef.current && Date.now() - cached.at < TOKEN_MAX_AGE_MS
    const token = fresh ? cached.token : gateway.createTranscriptionToken(sessionRef.current)
    prefetchToken()
    return token
  }, [prefetchToken])

  const refresh = useCallback(() => {
    if (!activeRef.current) setState('off')
    else if (hearingRef.current) setState('hearing')
    else if (playingRef.current) setState('speaking')
    else setState(processingRef.current ?? 'listening')
  }, [])

  const releaseUrl = () => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    urlRef.current = null
  }

  const stopPlayback = useCallback(() => {
    generationRef.current += 1
    queue.interrupt()
    audioRef.current?.pause()
    releaseUrl()
    playingRef.current = false
  }, [queue])

  const pump = useCallback(async () => {
    if (playingRef.current || !activeRef.current) return
    const item: SpeechItem | null = queue.next()
    if (!item) { refresh(); return }
    const generation = generationRef.current
    playingRef.current = true
    refresh()
    const finish = () => {
      if (generation !== generationRef.current) return
      releaseUrl()
      playingRef.current = false
      refresh()
      void pump()
    }
    try {
      const blob = await gateway.fetchSpeechClip(sessionRef.current, item.clipId)
      if (generation !== generationRef.current) return
      const audio = audioRef.current ?? new Audio()
      audioRef.current = audio
      urlRef.current = URL.createObjectURL(blob)
      audio.onended = finish
      audio.onerror = finish
      audio.src = urlRef.current
      await audio.play()
    } catch (failure) {
      if (failure instanceof DOMException && failure.name === 'NotAllowedError') setError(copy.voicePlaybackBlocked)
      finish()
    }
  }, [queue, refresh])

  const speak = useCallback((item: SpeechItem) => {
    if (!activeRef.current) return
    queue.enqueue(item)
    void pump()
  }, [queue, pump])

  const speakGuidance = useCallback((event: GuidanceEvent) => {
    if (event.speech_clip_id) speak({ kind: event.kind, clipId: event.speech_clip_id, text: event.text })
  }, [speak])

  const drain = useCallback(async () => {
    if (processingRef.current) return
    while (utterancesRef.current.length > 0 && activeRef.current) {
      const { wav, text: streamed } = utterancesRef.current.shift() as Utterance
      processingRef.current = 'transcribing'
      refresh()
      let text = ''
      try {
        // The stream already heard the whole utterance; uploading the WAV is only the fallback.
        // An empty live result is retried as an upload: the live model drops quiet speech the batch model still hears.
        if (streamed) text = await streamed.catch((failure: unknown) => { console.warn('Live transcription failed; uploading the recording.', failure); return '' })
        if (!text) text = (await gateway.transcribe(sessionRef.current, wav)).text.trim()
      } catch (failure) {
        setError(failure instanceof ApiError && failure.code === '40004_speech_unavailable' ? copy.voiceUnavailable : failure instanceof Error ? failure.message : copy.voiceUnavailable)
        continue
      }
      if (!text) { setError(copy.voiceNotHeard); continue }
      setError(null)
      processingRef.current = 'thinking'
      refresh()
      const reply = await sendRef.current(text)
      // A queued utterance supersedes this reply: it is shown but not spoken.
      if (reply?.speechClipId && utterancesRef.current.length === 0) speak({ kind: 'reply', clipId: reply.speechClipId, text: reply.guideText })
    }
    processingRef.current = null
    refresh()
  }, [refresh, speak])

  useEffect(() => {
    if (!active || muted) return
    const vad = createVad()
    const ring: Float32Array[] = []
    let utterance: Float32Array[] | null = null
    let frames = 0
    const capture = createCapture((frame) => {
      const rms = frameRms(frame)
      frames += 1
      if (frames % 3 === 0) setLevel(Math.min(1, rms * 8))
      const event = vad.push(rms, FRAME_MS, playingRef.current)
      if (event === 'start') {
        if (playingRef.current) stopPlayback()
        utterance = [...ring]
        streamRef.current?.close()
        streamRef.current = openTranscriptStream(takeToken())
        for (const early of ring) streamRef.current.push(early)
        hearingRef.current = true
        refresh()
      }
      if (utterance) { utterance.push(frame); streamRef.current?.push(frame) }
      else { ring.push(frame); if (ring.length > PRE_ROLL_FRAMES) ring.shift() }
      if (event === 'end' && utterance) {
        const wav = new Blob([encodeWav(concat(utterance), SAMPLE_RATE)], { type: 'audio/wav' })
        utterance = null
        ring.length = 0
        hearingRef.current = false
        const streamed = streamRef.current?.finish() ?? null
        streamed?.catch(() => undefined)
        streamRef.current = null
        utterancesRef.current.push({ wav, text: streamed })
        void drain()
        refresh()
      }
    })
    let cancelled = false
    setError(null)
    prefetchToken()
    capture.start().then(() => { if (cancelled) capture.stop() }, (failure: unknown) => { if (!cancelled) setError(microphoneMessage(failure)) })
    return () => {
      cancelled = true
      capture.stop()
      streamRef.current?.close()
      streamRef.current = null
      vad.reset()
      hearingRef.current = false
      setLevel(0)
      refresh()
    }
  }, [active, muted, queue, drain, refresh, stopPlayback, prefetchToken, takeToken])

  useEffect(() => {
    if (active) { refresh(); return }
    stopPlayback()
    utterancesRef.current = []
    hearingRef.current = false
    refresh()
  }, [active, refresh, stopPlayback])

  useEffect(() => () => { stopPlayback(); audioRef.current = null }, [stopPlayback])

  return { state, level, muted, setMuted, error, clearError: () => setError(null), speakGuidance }
}
